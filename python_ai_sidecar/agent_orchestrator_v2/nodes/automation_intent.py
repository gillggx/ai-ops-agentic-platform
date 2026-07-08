"""Conversational automation setup (草稿暫存區 P3b, 2026-07-09).

When the user is looking at a pipeline in chat and says「這張圖每小時巡檢，
任一機台超過 3 次 OOC 就告警」, we DON'T silently enable anything — automation
runs unattended + fires alarms, a consequential action. Per governance
(project_cowork_ui_handoff V63: dangerous/go-live actions confirmed in the
authed UI, never from one chat sentence), the agent only PARSES the intent
into a config and emits a CONFIRM card; the human confirms in the UI and the
FRONTEND executes the enable via the existing tested skills_v2 endpoints.

This module is the pure parse step: NL → {role, trigger, gate, outcome}. The
Java saveAutomation is the schema/readiness source of truth (e.g. patrol
requires an alarm judgment in the pipeline) — we don't re-implement that here;
if the config isn't enable-able the frontend surfaces Java's honest error.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.observability.episode_recorder import get_current_recorder

logger = logging.getLogger(
    "python_ai_sidecar.agent_orchestrator_v2.nodes.automation_intent")

# Display schedule strings the Java scheduler catalogue understands
# (normalizeScheduleSpec maps these deterministically).
_SCHEDULES = ["每 15 分鐘", "每 30 分鐘", "每 1 小時", "每 3 小時", "每天 08:00", "每天 20:00"]

_SYSTEM = f"""你是自動化設定解析器。使用者想把螢幕上這條 pipeline 設成自動執行。
把使用者的話解析成 JSON（只輸出 JSON）：

{{"role": "patrol" | "datacheck",
  "trigger": {{"kind": "schedule", "schedule": "<下列其一>"}},
  "alarm_gate": "<一句話描述告警條件，patrol 才要>",
  "outcome": "<一句話描述命中後做什麼，patrol 才要>",
  "summary": "<一句話人看的總結>"}}

判準：
- 有「告警 / alarm / 超過 / 就通知 / 異常提醒」等 → role=patrol，並填 alarm_gate + outcome。
- 只是「定時檢查 / 定期看 / 每天跑一次看資料」沒有告警 → role=datacheck，alarm_gate/outcome 留空。
- schedule 必須是這清單其一（挑最接近的）：{_SCHEDULES}。使用者說「每小時」→「每 1 小時」；
  「每 15 分」→「每 15 分鐘」；沒講頻率 → 「每 1 小時」。
只輸出 JSON。"""

_VALID_ROLES = {"patrol", "datacheck"}


async def parse_automation(user_msg: str, snapshot: Dict[str, Any]) -> Dict[str, Any] | None:
    """NL → automation config dict, or None on parse failure (caller falls
    through). Deterministically clamps role + schedule to valid values."""
    client = get_llm_client()
    payload = (
        "使用者這句話：\n" + user_msg[:400]
        + "\n\npipeline 節點（id/block）：\n"
        + json.dumps([{"id": n.get("id"), "block": n.get("block_id")}
                      for n in (snapshot.get("nodes") or [])], ensure_ascii=False)[:600]
    )
    try:
        resp = await client.create(system=_SYSTEM,
                                   messages=[{"role": "user", "content": payload}],
                                   max_tokens=500)
        raw = (resp.text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.rstrip().endswith("```"):
                raw = raw.rstrip()[:-3]
        cfg = json.loads(raw)
    except Exception as ex:  # noqa: BLE001
        logger.warning("automation parse failed (%s)", ex)
        return None
    rec = get_current_recorder()
    if rec:
        rec.record("llm_usage", agent="planner",
                   input_tokens=getattr(resp, "input_tokens", None),
                   output_tokens=getattr(resp, "output_tokens", None),
                   latency_ms=getattr(resp, "latency_ms", None))

    role = str((cfg or {}).get("role") or "").lower()
    if role not in _VALID_ROLES:
        role = "patrol" if (cfg or {}).get("alarm_gate") else "datacheck"
    trig = (cfg or {}).get("trigger") or {}
    schedule = str(trig.get("schedule") or "")
    if schedule not in _SCHEDULES:
        schedule = "每 1 小時"
    out: Dict[str, Any] = {
        "role": role,
        "trigger": {"kind": "schedule", "schedule": schedule},
        "summary": str((cfg or {}).get("summary") or "")[:200],
    }
    if role == "patrol":
        out["alarm_gate"] = str((cfg or {}).get("alarm_gate") or "")[:300]
        out["outcome"] = str((cfg or {}).get("outcome") or "命中時告警")[:200]
    return out
