"""Shared StreamEvent → `pb_glass_*` mapping. Used by both the chat
orchestrator's build_pipeline_live tool AND the /build/continue router so
continuation events reach the frontend dispatcher in the same shape as the
first build pass."""

from __future__ import annotations

from typing import Any, Optional

from python_ai_sidecar.agent_builder.session import StreamEvent


def wrap_build_event_for_chat(
    evt: StreamEvent, session_id: str
) -> Optional[dict[str, Any]]:
    evt_type = evt.type
    data = evt.data or {}
    payload: dict[str, Any] = {"session_id": session_id}

    if evt_type == "chat":
        payload["type"] = "pb_glass_chat"
        payload["content"] = data.get("content", "")
    elif evt_type == "operation":
        payload["type"] = "pb_glass_op"
        payload["op"] = data.get("op")
        payload["args"] = data.get("args") or {}
        payload["result"] = data.get("result") or {}
    elif evt_type == "error":
        payload["type"] = "pb_glass_error"
        payload["message"] = data.get("message", "")
        payload["hint"] = data.get("hint")
        payload["op"] = data.get("op")
    elif evt_type == "done":
        payload["type"] = "pb_glass_done"
        payload["status"] = data.get("status", "finished")
        payload["pipeline_json"] = data.get("pipeline_json")
        payload["summary"] = data.get("summary")
    elif evt_type == "plan":
        payload["type"] = "plan"
        payload["items"] = data.get("items") or []
    elif evt_type == "plan_update":
        payload["type"] = "plan_update"
        payload["id"] = data.get("id")
        payload["status"] = data.get("status")
        payload["note"] = data.get("note")
    elif evt_type == "continuation_request":
        payload["type"] = "continuation_request"
        payload["session_id"] = data.get("session_id")
        payload["turns_used"] = data.get("turns_used")
        payload["ops_count"] = data.get("ops_count")
        payload["completed"] = data.get("completed") or []
        payload["remaining"] = data.get("remaining") or []
        payload["estimate"] = data.get("estimate")
        payload["options"] = data.get("options") or []
    elif evt_type == "glass_usage":
        payload["type"] = "glass_usage"
        for k in (
            "turn", "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens",
        ):
            payload[k] = data.get(k, 0)
    elif evt_type == "glass_progress":
        payload["type"] = "glass_progress"
        for k in ("turn_used", "turn_budget", "absolute_max", "percent", "warning"):
            payload[k] = data.get(k)
    else:
        return None
    return payload
