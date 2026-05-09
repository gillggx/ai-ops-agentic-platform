"""Shared StreamEvent → `pb_glass_*` mapping.

Used by the chat orchestrator's build_pipeline_live tool to relay graph
build events into the chat SSE channel. Phase 10-B: handles both the
legacy v1 events (chat/operation/error) AND the v2 events
(plan_proposed/op_completed/build_finalized/...) emitted by graph_build.

Frontend (chat panel + lite canvas) only knows about pb_glass_*; this
wrapper is the only place that translates v2 op shape → v1 args/result
shape so existing apply_glass_op() logic keeps working."""

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

    # ── Phase 10-B: v2 graph_build events ─────────────────────────────
    elif evt_type == "plan_proposed":
        # Surface as a chat narration so the user sees what the agent intends.
        # Lite canvas already shows nothing (no nodes added yet) so this is
        # mainly for the chat column.
        summary = (data.get("summary") or "").strip()
        if not summary:
            return None
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"📋 計畫：{summary}"
    elif evt_type == "plan_repaired":
        ok = data.get("ok")
        if not ok:
            return None  # silent — repair will retry or escalate
        payload["type"] = "pb_glass_chat"
        attempt = data.get("attempt", 1)
        payload["content"] = f"🔧 自動修正了 plan（第 {attempt} 次）"
    elif evt_type == "op_completed":
        # Translate v2 op → v1 args/result so apply_glass_op keeps working.
        op_obj = data.get("op") or {}
        result = data.get("result") or {}
        op_type = op_obj.get("type")
        v1_args = _v2_op_to_v1_args(op_obj)
        if v1_args is None:
            return None
        payload["type"] = "pb_glass_op"
        payload["op"] = op_type
        payload["args"] = v1_args
        payload["result"] = result
    elif evt_type == "op_error":
        op_obj = data.get("op") or {}
        msg = op_obj.get("error_message") or "(no error msg)"
        payload["type"] = "pb_glass_error"
        payload["message"] = f"op#{data.get('cursor')} ({op_obj.get('type')}) failed: {msg}"
        payload["op"] = op_obj.get("type")
        payload["hint"] = None
    elif evt_type == "build_finalized":
        payload["type"] = "pb_glass_done"
        payload["status"] = "finished" if data.get("ok") else "failed"
        payload["summary"] = data.get("summary") or ""
        # build_finalized doesn't carry pipeline_json itself — done event will.
        payload["pipeline_json"] = None
    elif evt_type == "runtime_check_ok":
        # Phase 10-C Fix 4 — finalize dry-run passed. Surface as a small
        # narration so user knows the canvas IS runnable; not just built.
        n = data.get("node_count") or 0
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"✅ Runtime check：pipeline 跑通 ({n} nodes 都 ok)"
    elif evt_type == "runtime_check_failed":
        failed = data.get("failures") or []
        first = failed[0] if failed else {}
        nid = first.get("node_id") or "?"
        err = first.get("error") or data.get("error") or "(unknown)"
        payload["type"] = "pb_glass_error"
        payload["message"] = f"⚠ Runtime check 發現問題：node {nid} — {str(err)[:200]}"
        payload["op"] = None
        payload["hint"] = "Pipeline 已建在 canvas，請在 builder 開啟 node 修參數後再 run。"
    elif evt_type == "runtime_check_timeout":
        payload["type"] = "pb_glass_chat"
        payload["content"] = (
            f"⏱ Runtime check 超時（>{data.get('timeout_sec', 10)}s）— "
            "已建好 pipeline 但無法在 build 階段先驗一遍，請手動 run。"
        )
    elif evt_type == "runtime_check_skipped":
        reason = data.get("reason") or "unknown"
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"⏭ Runtime check 跳過（{reason}）"
    elif evt_type == "runtime_check_no_data":
        msg = data.get("message") or "pipeline 跑通但沒回任何資料"
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"ℹ {msg}"
    elif evt_type in (
        "plan_validating",   # noisy — internal validation step
        "op_dispatched",     # paired with op_completed; redundant
        "op_repaired",       # retry will surface as op_completed/op_error
        "confirm_pending",   # MUST NOT happen in chat (skip_confirm=True)
        "confirm_received",  # builder-only ACK
    ):
        return None
    else:
        return None
    return payload


def _v2_op_to_v1_args(op_obj: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Translate a v2 Op dict (with type + typed fields) into the v1 args
    dict that glass-ops.ts apply_glass_op() expects."""
    op_type = op_obj.get("type")
    if op_type == "add_node":
        return {
            "block_name": op_obj.get("block_id"),
            "block_version": op_obj.get("block_version") or "1.0.0",
            "params": op_obj.get("params") or {},
        }
    if op_type == "connect":
        return {
            "from_node": op_obj.get("src_id"),
            "from_port": op_obj.get("src_port"),
            "to_node": op_obj.get("dst_id"),
            "to_port": op_obj.get("dst_port"),
        }
    if op_type == "set_param":
        params = op_obj.get("params") or {}
        return {
            "node_id": op_obj.get("node_id"),
            "key": params.get("key"),
            "value": params.get("value"),
        }
    if op_type == "remove_node":
        return {"node_id": op_obj.get("node_id")}
    if op_type == "run_preview":
        return {"node_id": op_obj.get("node_id")}
    return None
