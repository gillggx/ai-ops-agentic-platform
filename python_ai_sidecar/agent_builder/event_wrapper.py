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
        # Phase 10-D: include expected_outputs so chat user (no confirm card)
        # still gets the "📊 跑完會看到 …" preview.
        summary = (data.get("summary") or "").strip()
        if not summary:
            return None
        outputs = data.get("expected_outputs") or []
        lines = [f"📋 計畫：{summary}"]
        if outputs:
            lines.append("")
            lines.append("📊 跑完會看到：")
            for o in outputs[:6]:
                lines.append(f"  • {o}")
        payload["type"] = "pb_glass_chat"
        payload["content"] = "\n".join(lines)
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
    # ── v16: macro+chunk events ───────────────────────────────────────
    elif evt_type == "macro_plan_proposed":
        summary = (data.get("summary") or "").strip()
        steps = data.get("macro_plan") or []
        n = data.get("n_steps") or len(steps)
        lines = [f"📋 計畫：{summary}" if summary else f"📋 計畫（{n} 步）"]
        for s in steps[:8]:
            idx = s.get("step_idx", "?")
            txt = s.get("text") or ""
            kind = s.get("expected_kind") or ""
            kind_tag = f" [{kind}]" if kind else ""
            lines.append(f"  {idx}. {txt}{kind_tag}")
        if len(steps) > 8:
            lines.append(f"  …+{len(steps) - 8} more")
        payload["type"] = "pb_glass_chat"
        payload["content"] = "\n".join(lines)
    elif evt_type == "chunk_compiled":
        idx = data.get("step_idx") or "?"
        text_val = data.get("step_text") or ""
        n_ops = data.get("n_ops") or 0
        attempts = data.get("attempts", 1)
        attempt_tag = f"（第 {attempts} 次）" if attempts > 1 else ""
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"⚙ Step {idx} 編譯 → {n_ops} ops{attempt_tag}：{text_val}"
    elif evt_type in ("compile_chunk_error", "compile_chunk_failed"):
        idx = data.get("step_idx") or "?"
        err = (data.get("error") or "").strip()
        if not err:
            return None
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"⚠ Step {idx} 編譯失敗：{err[:200]}"
    elif evt_type == "macro_plan_too_vague":
        reason = (data.get("reason") or "").strip()
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"❓ 需求太模糊，無法產生計畫{f'：{reason}' if reason else ''}"
    elif evt_type == "macro_plan_failed":
        reason = (data.get("reason") or data.get("error") or "").strip()
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"❌ Macro plan 產生失敗{f'：{reason}' if reason else ''}"
    # ── v30.17c (2026-05-17): v30 ReAct events → chat pb_glass_* ───────
    # Before v30.17c these events fell through to the silent-drop block at
    # the bottom → chat UI saw NOTHING during a v30 build → LLM wrote
    # apology summaries (「抱歉，系統限制」). After v30.14 flipped chat
    # to v30 default, this was the missing user-facing fix.
    # Verify any future change via tools/ui_consistent_verify/chat_verify.py.
    elif evt_type == "goal_plan_proposed":
        phases = data.get("phases") or []
        summary = (data.get("plan_summary") or "").strip()
        lines = []
        if summary:
            lines.append(f"📋 Plan：{summary}")
        if phases:
            lines.append(f"📊 {len(phases)} 個 phase：")
            for p in phases[:8]:
                pid = p.get("id", "?")
                goal = (p.get("goal") or "").strip()
                exp = (p.get("expected") or "").strip()
                lines.append(f"  • {pid} [{exp}] {goal[:60]}")
        if not lines:
            return None
        payload["type"] = "pb_glass_chat"
        payload["content"] = "\n".join(lines)
        # v30.17i — structured plan data alongside text so a frontend
        # (ChatPanel.PlanCard) can render a proper card with per-phase
        # status badges. AIAgentPanel ignores the extra field and keeps
        # showing the text bubble; no regression.
        payload["plan"] = {
            "summary": summary,
            "phases": [{
                "id": p.get("id"),
                "goal": p.get("goal"),
                "expected": p.get("expected"),
                "auto_injected": bool(p.get("auto_injected")),
            } for p in phases],
        }
    elif evt_type == "goal_plan_confirmed":
        auto = data.get("auto_confirmed")
        n = len(data.get("phases") or [])
        suffix = "（自動確認）" if auto else ""
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"✓ Plan 已確認，開始建構 {n} 個 phase{suffix}"
        # v30.17i — signal plan confirmation so the card can flip from
        # "proposed" to "running" state.
        payload["plan_confirmed"] = {"auto": bool(auto), "n_phases": n}
    elif evt_type in ("goal_plan_rejected", "goal_plan_refused"):
        payload["type"] = "pb_glass_chat"
        payload["content"] = "✗ Plan 被拒絕，建構中止"
    elif evt_type == "phase_action":
        # v30.17h (2026-05-17) — emit pb_glass_op in the v27-compatible
        # shape so applyGlassOp can paint the Lite Canvas. Previously this
        # branch flattened args into a text summary, which made the canvas
        # invisible (LiteCanvasOverlay rendered nothing). Now we pass the
        # raw structured args + result through as the top-level args/result,
        # and stash v30-specific phase context under underscore-prefixed
        # keys (`_phase_id` / `_round` / `_args_summary`) so chat log can
        # still show the phase/round prefix without breaking applyGlassOp.
        pid = data.get("phase_id") or "?"
        rnd = data.get("round") or "?"
        tool = data.get("tool") or "?"
        args_summary = data.get("args_summary") or ""
        result_summary = data.get("result_summary") or ""
        raw_args = data.get("tool_args_raw")
        raw_result = data.get("action_result_raw")

        payload["type"] = "pb_glass_op"
        payload["op"] = tool  # no "v30:" prefix — matches OP_LABEL_MAP keys
        # args: structured raw + phase metadata. dict.copy() so caller
        # can't accidentally mutate the trace.
        args_out: dict[str, Any] = dict(raw_args) if isinstance(raw_args, dict) else {}
        args_out["_phase_id"] = pid
        args_out["_round"] = rnd
        args_out["_args_summary"] = str(args_summary)[:200]
        payload["args"] = args_out
        # result: structured raw + summary text
        result_out: dict[str, Any] = dict(raw_result) if isinstance(raw_result, dict) else {}
        result_out["_summary"] = str(result_summary)[:300]
        payload["result"] = result_out
    elif evt_type == "phase_completed":
        pid = data.get("phase_id") or "?"
        rationale = (data.get("rationale") or "").strip()
        block = data.get("advanced_by_block")
        node = data.get("advanced_by_node")
        extra = f"（{node} [{block}]）" if (block and node) else ""
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"✓ Phase {pid} 完成{extra}：{rationale[:120]}"
        # v30.17i — structured phase status for PlanCard
        payload["phase_update"] = {
            "phase_id": pid, "status": "completed",
            "rationale": rationale[:200],
            "block_id": block, "node_id": node,
        }
    elif evt_type == "phase_revise_started":
        pid = data.get("phase_id") or "?"
        reason = (data.get("reason") or "").strip()
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"⏸ Phase {pid} 卡住，反思中（{reason[:80]}）"
        payload["phase_update"] = {
            "phase_id": pid, "status": "revising", "reason": reason[:200],
        }
    elif evt_type == "phase_revise_retry":
        pid = data.get("phase_id") or "?"
        alt = (data.get("alternative") or "").strip()
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"↻ Phase {pid} 換策略再試：{alt[:120]}"
        payload["phase_update"] = {
            "phase_id": pid, "status": "revising_retry", "alternative": alt[:200],
        }
    elif evt_type == "phase_fast_forward_report":
        # One block satisfied multiple phases at once
        block = data.get("advanced_by_block") or "?"
        node = data.get("advanced_by_node") or "?"
        completed = data.get("phases_completed") or []
        ids = ", ".join(c.get("id", "?") for c in completed)
        payload["type"] = "pb_glass_chat"
        payload["content"] = (
            f"⚡ Fast-forward：{len(completed)} 個 phase ({ids}) 由 "
            f"{node} [{block}] 一次涵蓋"
        )
    elif evt_type == "handover_pending":
        # In chat (skip_confirm=True) v30.17b auto-takes-over so this
        # shouldn't normally fire, but if it does (skip_confirm flag flaked
        # OR caller forgot), still surface so user knows something halted.
        pid = data.get("failed_phase_id") or "?"
        reason = (data.get("reason") or "").strip()
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"⚠ Phase {pid} 失敗：{reason[:200]}"
        payload["phase_update"] = {
            "phase_id": pid, "status": "failed", "reason": reason[:200],
        }
    elif evt_type == "handover_chosen":
        choice = data.get("choice") or "?"
        auto = data.get("auto_chosen")
        suffix = "（自動）" if auto else ""
        pid = data.get("failed_phase_id") or "?"
        payload["type"] = "pb_glass_chat"
        payload["content"] = f"↳ Phase {pid} 處置：{choice}{suffix}"
        payload["phase_update"] = {
            "phase_id": pid, "status": f"handover_{choice}", "auto": bool(auto),
        }
    elif evt_type == "build_partial":
        # status update for partial build (some phases failed, take_over chosen)
        payload["type"] = "pb_glass_chat"
        payload["content"] = "⚠ Build 部分完成（有 phase 失敗，已採納部分結果）"
    # Silent v30 events that would spam chat without adding signal
    elif evt_type in (
        "phase_round",                 # each ReAct round; phase_action covers it
        "phase_observation",           # tool_result preview, internal
        "phase_verifier_no_match",     # verifier internal, retry will surface
        "phase_round_paused",          # debug step-mode only
        "goal_plan_confirm_required",  # interrupt — v30.17a auto-skips in chat
    ):
        return None

    elif evt_type in (
        "plan_validating",   # noisy — internal validation step
        "op_dispatched",     # paired with op_completed; redundant
        "op_repaired",       # retry will surface as op_completed/op_error
        "confirm_pending",   # MUST NOT happen in chat (skip_confirm=True)
        "confirm_received",  # builder-only ACK
        "canvas_reset",      # internal flag, no user-facing meaning in chat
        "clarify_skipped",   # internal — chat mode skips clarify gate
        "clarify_received",  # builder-only
        "inspection_clean",  # no-news-is-good-news, don't spam chat
        "inspection_issues_found",  # logged sidecar-side; soft issues shouldn't alarm
        "reflect_op_failed",       # internal retry mechanic
        "plan_op_reflected",       # internal retry mechanic
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
