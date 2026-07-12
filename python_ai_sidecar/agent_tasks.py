"""Agent Tasks (V85, 2026-07-11) — 工作與畫面非同步.

長工作（build / skill_run）改成 in-process 背景 asyncio task 執行；SSE 回應
只是「訂閱者」— 客戶端斷線（鎖屏 / 關分頁 / 換裝置）只取消訂閱，不取消工作。

- 事件全量緩衝在記憶體（單一 build 約 40-300 個小 JSON），重連 = 回放緩衝
  再接即時佇列 → 進度不漏。
- 完成 / 失敗時把「收尾事件」（pb_glass_done 起，含圖卡 payload）持久化到
  Java `agent_tasks`，讓「離線期間完成」的工作在任何裝置回放結果 — 即使
  sidecar 已重啟、記憶體緩衝不在了。
- sidecar 重啟中的 running task 一律死亡（與現況相同）；啟動時不做復活，
  由 Java 端 status=running 但 registry 查無 → 回報 interrupted。

單一 event loop 前提：事件派發（append + fan-out）與訂閱掛載（attach +
snapshot copy）都是同步區塊，彼此不可能交錯，回放不重複不漏。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger("python_ai_sidecar.agent_tasks")

# SSE-shaped event: {"event": str, "data": json-str}
Event = Dict[str, str]

_HISTORY_CAP = 2000          # runaway guard；正常 build 遠低於此
_REGISTRY_CAP = 200          # 完成的 task 留在記憶體供快速回放，超過丟最舊
_TERMINAL_KEEP_EVENTS = 40   # 持久化收尾事件數上限（done + 圖卡 + run 摘要）


@dataclass
class AgentTask:
    task_id: str
    kind: str                     # 'build' | 'skill_run'
    chat_session_id: str
    user_id: int
    goal: str = ""
    status: str = "running"       # running | finished | failed
    created_at: float = field(default_factory=time.time)
    history: List[Event] = field(default_factory=list)
    queues: List[asyncio.Queue] = field(default_factory=list)

    def public_dict(self) -> Dict[str, Any]:
        import datetime as _dt
        return {
            "task_id": self.task_id, "kind": self.kind,
            "chat_session_id": self.chat_session_id, "status": self.status,
            "goal": self.goal,
            # ISO 字串 — 跟 Java 持久列同型別才能排序。曾直接放 epoch float，
            # 字串排序讓 "2026-…" 永遠贏 "1752…" → reattach 選到舊 task 回放。
            "created_at": _dt.datetime.fromtimestamp(
                self.created_at, tz=_dt.timezone.utc).isoformat(),
            "events_buffered": len(self.history),
        }


_REGISTRY: Dict[str, AgentTask] = {}


def get_task(task_id: str) -> Optional[AgentTask]:
    return _REGISTRY.get(task_id)


def tasks_for_session(chat_session_id: str) -> List[AgentTask]:
    return sorted(
        [t for t in _REGISTRY.values() if t.chat_session_id == chat_session_id],
        key=lambda t: t.created_at, reverse=True)


def _dispatch(task: AgentTask, ev: Event) -> None:
    if len(task.history) < _HISTORY_CAP:
        task.history.append(ev)
    for q in list(task.queues):
        try:
            q.put_nowait(ev)
        except Exception:  # noqa: BLE001 — a dead queue must not kill the run
            pass


def _finish(task: AgentTask) -> None:
    for q in list(task.queues):
        try:
            q.put_nowait(None)  # sentinel: stream over
        except Exception:  # noqa: BLE001
            pass
    # registry 容量控制：踢掉最舊的「已完成」task
    done = [t for t in _REGISTRY.values() if t.status != "running"]
    if len(done) > _REGISTRY_CAP:
        for t in sorted(done, key=lambda t: t.created_at)[: len(done) - _REGISTRY_CAP]:
            _REGISTRY.pop(t.task_id, None)


def _terminal_events(task: AgentTask) -> List[Event]:
    """收尾事件 = phase 進度（小，供計畫卡補打勾）+ 最後一個 pb_glass_done 起
    的尾段（done 卡/圖卡/run 摘要）。單一事件 >300KB（通常是 pb_run_done 的
    完整 node_results）不進持久層。"""
    idx = 0
    for i, ev in enumerate(task.history):
        if ev.get("event") == "pb_glass_done":
            idx = i
    # 完成後回放要能把計畫卡打勾 — phase_update 事件每個 ~300B，全留。
    phase_evs = [ev for ev in task.history[:idx]
                 if ev.get("event") == "pb_glass_chat"
                 and '"phase_update"' in (ev.get("data") or "")][:30]
    tail = [ev for ev in task.history[idx:][:_TERMINAL_KEEP_EVENTS]
            if len(ev.get("data") or "") <= 300_000]
    return phase_evs + tail


async def _persist(task: AgentTask) -> None:
    try:
        from python_ai_sidecar.clients.java_client import JavaAPIClient
        from python_ai_sidecar.config import CONFIG
        java = JavaAPIClient(CONFIG.java_api_url, CONFIG.java_internal_token,
                             timeout_sec=CONFIG.java_timeout_sec)
        body: Dict[str, Any] = {
            "kind": task.kind,
            "chat_session_id": task.chat_session_id,
            "user_id": task.user_id,
            "status": task.status,
            "goal": task.goal[:500],
        }
        if task.status != "running":
            body["terminal_events"] = json.dumps(
                _terminal_events(task), ensure_ascii=False)
        await java._put_data(f"/internal/agent-tasks/{task.task_id}", body)
    except Exception as ex:  # noqa: BLE001 — persistence is best-effort
        logger.warning("agent_task persist failed (%s): %s", task.task_id, ex)


def start_task(
    *, kind: str, chat_session_id: str, user_id: int, goal: str,
    gen: AsyncGenerator[Event, None],
) -> AgentTask:
    """Spawn the work as a DETACHED asyncio task; return immediately."""
    task = AgentTask(
        task_id=f"task-{uuid.uuid4().hex[:12]}", kind=kind,
        chat_session_id=chat_session_id, user_id=user_id, goal=goal)
    _REGISTRY[task.task_id] = task

    async def _run() -> None:
        failed = False
        try:
            async for ev in gen:
                _dispatch(task, ev)
                if ev.get("event") == "error":
                    failed = True
        except Exception as ex:  # noqa: BLE001 — surface, never swallow
            logger.exception("agent_task %s crashed", task.task_id)
            failed = True
            _dispatch(task, {"event": "error", "data": json.dumps(
                {"message": f"task crashed: {ex.__class__.__name__}: {str(ex)[:200]}"},
                ensure_ascii=False)})
            _dispatch(task, {"event": "done", "data": json.dumps({"status": "failed"})})
        finally:
            task.status = "failed" if failed else "finished"
            _finish(task)
            await _persist(task)
            logger.info("agent_task %s %s (%d events, session=%s)",
                        task.task_id, task.status, len(task.history),
                        task.chat_session_id)

    asyncio.ensure_future(_run())
    # 建立時就先落一筆 running（斷線期間另一台裝置才查得到）
    asyncio.ensure_future(_persist(task))
    return task


async def subscribe(task: AgentTask) -> AsyncGenerator[Event, None]:
    """Replay buffered history, then follow live events until the run ends.

    Detach-safe: generator cleanup (client disconnect) only removes the queue.
    """
    q: asyncio.Queue = asyncio.Queue()
    # 同步區塊：先掛佇列再快照 — 不漏不重（單一 event loop）。
    task.queues.append(q)
    snapshot = list(task.history)
    try:
        for ev in snapshot:
            yield ev
        # 佇列從 attach 之後的事件開始（replay 期間到達的也在裡面）。
        # 已完成的 task 可能從未對這條新佇列送 sentinel — 用 timeout poll
        # 避免死等，同時確保完成前最後幾個事件不被丟掉。
        while True:
            if task.status != "running" and q.empty():
                return
            try:
                ev = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if ev is None:
                return
            yield ev
    finally:
        try:
            task.queues.remove(q)
        except ValueError:
            pass
