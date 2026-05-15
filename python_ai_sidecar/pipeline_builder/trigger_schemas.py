"""Canonical trigger payload shapes — what shape of `inputs` dict gets
fed to a pipeline at runtime depending on its trigger kind.

Surfaced to LLM at build time so it knows what fields the pipeline can
read off the trigger event. Without this, the agent has to guess based
on prior beliefs and often invents fields that don't exist.

Pipelines declare trigger kind in `pipeline_json.metadata.trigger_kind`.
When set, macro_plan + compile_chunk dump the matching schema into the
prompt's USER NEED section.
"""
from __future__ import annotations

from typing import Any


TriggerKind = str  # "process_event" | "alarm" | "auto_patrol" | "manual"


# Each schema is documented as the literal Python dict the pipeline will
# receive at runtime. Comments in description string explain semantics.
TRIGGER_PAYLOAD_SCHEMAS: dict[str, dict[str, Any]] = {
    # Fired per process event (most common — "when EQP-01 step STEP_001
    # finishes, run X"). Payload mirrors process_history record exactly.
    "process_event": {
        "description": (
            "每筆 process 完成時觸發。Payload 是 process_history 一筆 record "
            "的完整 nested shape — 與 block_process_history(nested=true) 的 "
            "output 同結構，可直接用 path 文法引用。"
        ),
        "shape": {
            "eventTime": "2026-05-15T10:32:18.912Z (ISO8601 string)",
            "toolID": "EQP-01",
            "lotID": "LOT-0517",
            "step": "STEP_001",
            "spc_status": "PASS | OOC",
            "fdc_classification": "GOOD | DRIFT | FAULT (or null)",
            "spc_charts": [
                {"name": "xbar_chart", "value": 13.91, "ucl": 17.5, "lcl": 12.5,
                 "is_ooc": False, "status": "PASS"},
                {"name": "r_chart", "value": 832.7, "ucl": 880, "lcl": 820,
                 "is_ooc": False, "status": "PASS"},
            ],
            "spc_summary": {"ooc_count": 0, "total_charts": 5,
                            "ooc_chart_names": []},
            "APC": {"objectID": "APC-01", "mode": "auto", "parameters": {}},
            "DC": {"chamberID": "CH-A", "objectID": "DC-01", "parameters": {}},
            "RECIPE": {"objectID": "RECIPE-A", "recipe_version": 1, "parameters": {}},
            "FDC": {"classification": "GOOD", "parameters": {}},
            "EC": {"parameters": {}},
        },
    },

    # Fired when an alarm is raised by another pipeline / external system.
    # Used by escalation pipelines / cross-alarm dedup logic.
    "alarm": {
        "description": (
            "Alarm event 觸發。Payload 包含 alarm metadata + 原 source pipeline "
            "的 trigger context（讓下游 pipeline 知道是哪個 process / event 引發 alarm）。"
        ),
        "shape": {
            "alarm_id": 12345,
            "severity": "med",  # "low" | "med" | "high"
            "triggered_at": "2026-05-15T10:32:20.000Z",
            "source_pipeline_id": 42,
            "source_pipeline_name": "SPC OOC monitor",
            "rule_summary": "ooc_count >= 2",
            # The original event/payload that caused the source pipeline to fire.
            # Often a process_event shape — see "process_event" schema above.
            "source_payload": "<process_event dict>",
        },
    },

    # Fired by Auto-Patrol scheduler — fan-out across all equipment / steps.
    # Pipeline gets a single (tool_id, step) pair per fan-out execution.
    "auto_patrol": {
        "description": (
            "Auto-Patrol 排程觸發。Scheduler 把 target_scope 展開成多次執行，"
            "每次傳一組 (tool_id, step) 給 pipeline。Pipeline 要在 inputs 宣告 "
            "$tool_id + $step 接收。"
        ),
        "shape": {
            "tool_id": "EQP-01",
            "step": "STEP_001",
            "scheduled_at": "2026-05-15T10:30:00.000Z",
            "patrol_id": 7,
        },
    },

    # User clicked Run / passed inputs ad-hoc. Free-form dict — whatever
    # the caller supplies. Useful only as a "no canonical shape" marker.
    "manual": {
        "description": (
            "User 手動 trigger，inputs 自由 dict — 由 user 在 UI 填入或 API caller 帶入。"
            "Pipeline 宣告什麼 inputs 就拿到什麼，沒有保證的固定欄位。"
        ),
        "shape": {},
    },
}


def format_for_prompt(kind: str | None) -> str:
    """Return a markdown-ish block ready to drop into LLM prompt. Empty
    string when kind is unknown / None — caller should skip the section.
    """
    if not kind:
        return ""
    spec = TRIGGER_PAYLOAD_SCHEMAS.get(kind)
    if not spec:
        return ""
    import json
    shape_json = json.dumps(spec.get("shape") or {}, indent=2, ensure_ascii=False)
    return (
        f"\n📨 TRIGGER PAYLOAD ({kind}) — pipeline 跑起來時收到的 inputs shape:\n"
        f"  {spec.get('description', '')}\n"
        f"  Sample shape:\n```json\n{shape_json}\n```"
    )
