"""Conversation-first chat agent (Step 1 of CHAT_AGENT_LOOP_SPEC, 2026-07-09).

The current chat is a rigid classifier → graph dispatcher: every utterance is
forced into 4 buckets, and anything that doesn't fit ("你能做什麼" / "你不能
聊天") falls into a逼選 clarify card. It's a窗口 that can't just talk.

This is the standard agent shape instead (like cowork / Claude Code): ONE
Anthropic tool-use loop. The model sees the whole conversation + a persona +
well-described tools, and at each step decides — reply naturally OR call a
tool. No classifier, no graph, no forced cards.

Step 1 scope (this file): natural conversation + READ-ONLY tools only
(status / skill search / knowledge). The heavy tools (build_pipeline wrapping
the untouched Planner&Builder, modify, automation) arrive in Step 2 — the
spec builds conversation first so we can judge dialogue quality in isolation.

Gated by CHAT_AGENT_LOOP_ENABLED so it never touches prod until we flip it.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger("python_ai_sidecar.agent_orchestrator_v2.chat_agent_loop")

MAX_TOOL_ROUNDS = 6


def is_chat_agent_loop_enabled() -> bool:
    return os.environ.get("CHAT_AGENT_LOOP_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


_SYSTEM = """你是「AIOps 操作助理」，幫半導體製程的工程師 / 當班人員在這個平台上做事。
講繁體中文，專業、精準、直指核心，不說多餘客套。

你能幫的事（需要「動作」時才用下面的工具；工具沒涵蓋的先老實說）：
- 查目前的告警與機台現況（工具：get_current_status）
- 找平台上現成的分析 Skill（工具：search_skills）
- （即將接上，這一版還沒有工具）建 SPC / 趨勢圖、就地調整圖表、查平台知識、
  把圖存成 Skill 並設自動化

怎麼跟人互動（重要）：
- 直接自然講話。可以閒聊、可以解釋、可以回答「你能幫我做什麼」——用人話講清楚，
  **絕對不要**丟制式選單卡逼使用者選。
- 需要查東西 / 跑東西再呼叫工具；沒有合適工具（例如要「建圖」但這版還沒接上）就
  老實說「這個我還在接上，現在可以幫你查現況 / 找現成 Skill」。
- 不確定使用者要什麼時，用**一句話**問清楚即可，不要硬猜、也不要一次丟一堆問題。
- 使用者問候 / 問你是誰 / 問能力 → 自然回答，不要當成分析請求。"""


_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "get_current_status",
        "description": "查目前的告警與機台現況：有哪些 active alarm、嚴重度、哪台機台。"
                       "使用者問「現在狀況 / 有什麼告警 / 哪台機台有問題 / 最近怎樣」時用。",
        "input_schema": {"type": "object", "properties": {
            "equipment_id": {"type": "string", "description": "只看某台機台（可省略，省略=全部）"}
        }},
    },
    {
        "name": "search_skills",
        "description": "用關鍵字找平台上現成的分析 Skill（pipeline）。使用者想做某分析、"
                       "或問「有沒有現成的…」時，先用這個找有沒有可用的。",
        "input_schema": {"type": "object", "properties": {
            "query": {"type": "string", "description": "要找的分析主題，如「OOC 排名」「SPC 趨勢」"}
        }, "required": ["query"]},
    },
]


async def _dispatch(name: str, inp: Dict[str, Any], java: Any, user_id: int) -> Any:
    """Read-only tool handlers over the existing Java client. Fail-soft: any
    error returns a message the model can relay, never crashes the loop."""
    try:
        if name == "get_current_status":
            snap = await java.get_agent_context_snapshot(
                selected_equipment_id=inp.get("equipment_id") or None)
            return {"active_alarms": (snap or {}).get("active_alarms") or [],
                    "user_focus": (snap or {}).get("user_focus") or {},
                    "as_of": (snap or {}).get("as_of")}
        if name == "search_skills":
            skills = await java.search_published_skills(str(inp.get("query") or ""), top_k=5)
            return [{"slug": s.get("slug"), "name": s.get("name"),
                     "sub": s.get("sub"), "role": s.get("role")} for s in (skills or [])]
        return {"error": f"unknown tool {name}"}
    except Exception as ex:  # noqa: BLE001 — fail-soft
        logger.warning("chat tool %s failed: %s", name, ex)
        return {"error": f"工具 {name} 執行失敗：{str(ex)[:120]}"}


async def run_chat_agent(
    *, message: str, history: List[Dict[str, Any]], java: Any, user_id: int,
) -> AsyncIterator[Dict[str, Any]]:
    """Anthropic tool-use loop. Yields v1-style SSE events; the final assistant
    text is a `synthesis` event (same contract the orchestrator uses)."""
    client = get_llm_client()
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": message}]

    for _round in range(MAX_TOOL_ROUNDS):
        resp = await client.create(system=_SYSTEM, messages=messages,
                                   tools=_TOOLS, max_tokens=1500)
        # record the assistant turn (content blocks) for the next round
        messages.append({"role": "assistant", "content": resp.content or [{"type": "text", "text": resp.text}]})
        tool_uses = [b for b in (resp.content or [])
                     if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not tool_uses:
            # model answered in natural language — done
            yield {"type": "synthesis", "text": resp.text or ""}
            return
        # run every requested tool, feed results back
        results: List[Dict[str, Any]] = []
        for tu in tool_uses:
            logger.info("chat agent tool: %s(%s)", tu.get("name"),
                        json.dumps(tu.get("input") or {}, ensure_ascii=False)[:100])
            out = await _dispatch(str(tu.get("name")), tu.get("input") or {}, java, user_id)
            results.append({"type": "tool_result", "tool_use_id": tu.get("id"),
                            "content": json.dumps(out, ensure_ascii=False, default=str)})
        messages.append({"role": "user", "content": results})

    # ran out of rounds — answer with whatever the last text was
    yield {"type": "synthesis", "text": "（我想太久了，先講到這；你可以再說清楚一點我幫你查。）"}
