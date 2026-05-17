"""v30 agentic_phase_loop — ReAct round runner for one phase at a time.

For the active phase (state.v30_current_phase_idx), build observation prompt
from canvas snapshot + runtime schemas, ask LLM to take 1 action via
tool-use, apply the action, auto-preview if it added/connected/set_param,
check phase_done, advance round counter. Max MAX_REACT_ROUNDS per phase.

If a phase exhausts rounds without completion, set status=phase_revise_pending
so router sends to phase_revise_node. If revise also fails, halt_handover_node
takes over.

Tools available to LLM in this loop:
  - inspect_node_output(node_id, n_rows<=3)
  - inspect_block_doc(block_id)
  - add_node / connect / set_param / remove_node
  - phase_complete(rationale)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_builder.session import AgentBuilderSession
from python_ai_sidecar.agent_builder.tools import BuilderToolset, ToolError
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


MAX_REACT_ROUNDS = 8
MAX_INSPECT_CALLS_PER_ROUND = 5
STUCK_DETECTOR_WINDOW = 2  # last N actions checked for duplicate


_SYSTEM = """你在一個 pipeline build 的 ReAct loop 內，每 round 進行一次「觀察 -> 決定 -> 行動」。

== 當前 PHASE 規範 ==
prompt 會給你:
  - CURRENT PHASE: user 確認過的 goal (照這做，不要偏離)
  - expected: phase 完成類別 (raw_data / transform / verdict / chart / table / scalar / alarm)
  - AVAILABLE INPUTS: declared pipeline inputs + trigger payload + canvas 已有 nodes 的 runtime schema
  - 可用 tools 列表

== 每 round 1 動作原則 ==
你每 round **只發一個 tool call**，等系統執行完拿到結果 (auto-preview snapshot)，再
進入下個 round 觀察新狀態決定下個動作。**不要連 emit 多個 add_node**。

== 行動順序建議 ==
1. 看不懂上游資料? -> `inspect_node_output(node_id, n_rows=2)` (cap 3)
2. 不確定某 block? -> `inspect_block_doc(block_id)` 看完整 doc + column_docs
3. 確定要加 node -> `add_node(block_id, params)`
   (系統會自動跑 preview，下 round 你會看到 runtime schema)
4. 要 connect -> `connect(from_node, from_port, to_node, to_port)`
5. 改 param -> `set_param(node_id, key, value)`
6. 加錯了 -> `remove_node(node_id)`

== Phase 達成 — server 自動判定 (v30.1, 2026-05-16) ==
你**不需要**主動 call phase_complete。每次 mutating action (add_node/connect/...)
完成後，server 端的 phase_spanning_verifier 會：
  (a) 對照當前 phase.expected_output 看 block 的輸出有沒有達成
  (b) **bonus**: 同一 block 若同時涵蓋下個 phase 也會 fast-forward 自動跳過
      (e.g. block_spc_panel 一個 add_node 可同時完成 raw_data + verdict + chart 三個 phase)
  (c) 把實際算出的數值 (ooc_count=3 之類) 填進 outcome 報告給 user 看

所以你 **只需要做對的 add_node**，phase 推進是自動的。看到下 round prompt 顯示
你已在 phase[k+N] (跳了好幾個) 是正常的 — composite block 的好處。

phase_complete 工具仍保留作為「我認為這 phase 已達成」的 hint，但不會強制觸發
驗證 — 真正的判定永遠以 server verifier 為準。

== 禁忌 ==
- 不要 emit JSON ops list — 用 single tool call
- 不要在沒讀過 upstream runtime schema 時憑空寫 column 名 (用 inspect 先看)
- 不要重複加同一 block 同一 params (stuck detector 會擋)
- 認真讀 column_docs 的 hint 標記：
    [best] = 該 column 的常用模式
    [ok]   = 也可行，常有 (direct) vs (shortcut) 兩條等價路線可選
    [warn] = 注意事項 / 反直覺陷阱
  選哪條看當下 phase / canvas 狀態與你想表達的語意，不要盲目跟 [best]

== Param naming 嚴格規則 ==
add_node 的 `params` key 必須**100% 一字不差**從 inspect_block_doc 的 param_schema 抄過來。
**不要用同義詞替換**：
  X equipment_id  ->  block_process_history 用的是 tool_id，**不是** equipment_id
  X column_name   ->  block_filter 用的是 column，**不是** column_name
  X chart_type    ->  block_line_chart 用的是 type，**不是** chart_type
若不確定 -> 先 inspect_block_doc(block_id)，看 param_schema 列出的 EXACT param names。

== Round 預算 ==
別把所有 8 round 都拿來 inspect — 通常 inspect → add_node → (auto verifier) 2-3 round
就該推進到下個 phase。看到下 round 還在同一 phase 就表示上一動作 verifier 沒接受，
看 prompt 裡的 `phase_verifier_no_match` event 知道哪裡不對。
"""


async def agentic_phase_loop_node(state: BuildGraphState) -> dict[str, Any]:
    """Single ReAct round for the active phase.

    Returns state update with possibly:
      - v30_phase_round incremented (continue same phase)
      - v30_current_phase_idx incremented (phase done, advance)
      - status='phase_revise_pending' (round max hit)
      - status='handover_pending' (revise also failed; routed by phase_revise)
    """
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    round_n = state.get("v30_phase_round", 0)
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []

    if idx >= len(phases):
        # All phases done — graph router will send us to finalize
        logger.info("agentic_phase_loop: all phases done (idx=%d / %d)", idx, len(phases))
        return {}

    phase = phases[idx]
    pid = phase["id"]

    # Round cap check
    if round_n >= MAX_REACT_ROUNDS:
        logger.warning(
            "agentic_phase_loop: phase %s exhausted %d rounds — escalate to revise",
            pid, MAX_REACT_ROUNDS,
        )
        if tracer is not None:
            tracer.record_step(
                "agentic_phase_loop", status="round_max_hit",
                phase_id=pid, rounds=round_n,
            )
        return {
            "status": "phase_revise_pending",
            "sse_events": [_event("phase_revise_started", {
                "phase_id": pid, "reason": "max_rounds_no_progress",
            })],
        }

    # ── Build observation prompt ──────────────────────────────────────
    obs_md = _build_observation_md(state, phase)
    full_user_msg = obs_md

    # ── Reconstruct toolset for this round ────────────────────────────
    registry = SeedlessBlockRegistry()
    registry.load()
    base_pipeline_dict = state.get("final_pipeline") or state.get("base_pipeline")
    pipeline = (
        PipelineJSON.model_validate(base_pipeline_dict) if base_pipeline_dict
        else PipelineJSON(
            version="1.0", name="New Pipeline (v30)",
            metadata={"created_by": "agent_v30"},
            nodes=[], edges=[],
        )
    )
    transient = AgentBuilderSession.new(
        user_prompt=state.get("instruction", ""), base_pipeline=pipeline,
    )
    toolset = BuilderToolset(transient, registry)

    # ── LLM call with tools ───────────────────────────────────────────
    # v30 C-A2: maintain Anthropic tool-use loop properly across rounds.
    # Round 1: messages=[user(full observation)]
    # Round 2+: messages already end with user(tool_result_from_previous_round
    #          + fresh observation diff). Call LLM directly.
    client = get_llm_client()
    tool_specs = _build_tool_specs()
    phase_messages = list(
        (state.get("v30_phase_messages") or {}).get(pid, [])
    )
    if not phase_messages:
        # First round of this phase — seed with full observation
        phase_messages.append({"role": "user", "content": full_user_msg})

    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=phase_messages,
            tools=tool_specs,
            max_tokens=2048,
        )
    except Exception as ex:  # noqa: BLE001
        logger.warning("agentic_phase_loop: LLM call failed: %s", ex)
        if tracer is not None:
            tracer.record_step(
                "agentic_phase_loop", status="llm_error",
                phase_id=pid, round=round_n, error=str(ex)[:200],
            )
        # Treat as a wasted round — bump counter, continue
        return {
            "v30_phase_round": round_n + 1,
            "sse_events": [_event("phase_round", {
                "phase_id": pid, "round": round_n + 1, "max": MAX_REACT_ROUNDS,
                "error": str(ex)[:120],
            })],
        }

    # Extract tool_use from response + capture full assistant content
    # for conversation continuity.
    tool_call = _extract_tool_call(resp)
    assistant_content = _extract_assistant_content(resp)

    # ── v30.1.1 (2026-05-16): record raw LLM call too (token usage +
    # ground-truth raw_response for cross-checking decision_records). ─
    if tracer is not None:
        try:
            # Use the user message we sent THIS round — for round 1 it's
            # the full observation; for subsequent rounds it's the diff.
            last_user_content = ""
            if phase_messages:
                last_user = next(
                    (m for m in reversed(phase_messages) if m.get("role") == "user"),
                    None,
                )
                if last_user is not None:
                    c = last_user.get("content")
                    if isinstance(c, str):
                        last_user_content = c
                    elif isinstance(c, list):
                        # round>=2: list of content parts (tool_result + text)
                        parts = []
                        for p in c:
                            if isinstance(p, dict):
                                if p.get("type") == "text":
                                    parts.append(p.get("text") or "")
                                elif p.get("type") == "tool_result":
                                    parts.append(f"[tool_result: {str(p.get('content',''))[:300]}]")
                        last_user_content = "\n".join(parts)
            raw_resp_text = ""
            if assistant_content:
                # serialize for debug — small
                raw_resp_text = str(assistant_content)[:8000]
            tracer.record_llm(
                "agentic_phase_loop",
                system=_SYSTEM,
                user_msg=last_user_content,
                raw_response=raw_resp_text,
                parsed=tool_call,
                resp=resp,
                phase_id=pid, round=round_n + 1,
            )
        except Exception as ex:  # noqa: BLE001
            logger.info("trace.record_llm failed (non-fatal): %s", ex)

    # ── v30.1.1 (2026-05-16): empathetic-debug decision record ───────
    # Capture: structured user_msg sections, LLM text reasoning, and
    # server-computed candidate analysis. This is what lets us answer
    # "why did LLM pick X?" without grepping the prompt string.
    if tracer is not None:
        try:
            from python_ai_sidecar.agent_builder.graph_build.trace_helpers import (
                build_decision_metadata, extract_llm_text_blocks,
                structure_user_msg_sections,
            )
            picked_block_name = None
            if tool_call and tool_call.get("name") == "add_node":
                picked_block_name = (tool_call.get("args") or {}).get("block_name")
            phases_all = state.get("v30_phases") or []
            remaining = phases_all[idx + 1:]
            sections = structure_user_msg_sections(
                current_phase=phase,
                all_phases=phases_all,
                current_idx=idx,
                declared_inputs=(state.get("base_pipeline") or {}).get("inputs") or [],
                exec_trace=state.get("exec_trace") or {},
                recent_actions=(state.get("v30_phase_recent_actions") or {}).get(pid, []),
                catalog_brief_text=_build_catalog_brief(),
                instruction=state.get("instruction") or "",
            )
            decision_meta = build_decision_metadata(
                phase=phase, remaining_phases=remaining,
                registry=registry, actual_pick_block=picked_block_name,
            )
            tracer.record_decision(
                node="agentic_phase_loop",
                phase_id=pid, round=round_n + 1,
                user_msg_sections=sections,
                llm_response={
                    "text_blocks": extract_llm_text_blocks(resp),
                    "tool_use": (
                        {"name": tool_call.get("name"), "input": tool_call.get("args")}
                        if tool_call else None
                    ),
                },
                decision_metadata=decision_meta,
            )
        except Exception as ex:  # noqa: BLE001 — tracing must never break flow
            logger.info("trace.record_decision failed (non-fatal): %s", ex)

    if tool_call is None:
        logger.info("agentic_phase_loop: phase %s round %d — no tool call", pid, round_n + 1)
        # Append assistant turn even if no tool — preserves dialogue.
        if assistant_content:
            phase_messages.append({"role": "assistant", "content": assistant_content})
        new_msgs = dict(state.get("v30_phase_messages") or {})
        new_msgs[pid] = phase_messages
        return {
            "v30_phase_round": round_n + 1,
            "v30_phase_messages": new_msgs,
            "sse_events": [_event("phase_round", {
                "phase_id": pid, "round": round_n + 1, "max": MAX_REACT_ROUNDS,
                "no_action": True,
            })],
        }

    tool_name = tool_call["name"]
    tool_args = tool_call.get("args") or {}
    tool_use_id = tool_call.get("id")

    # ── Stuck detector ────────────────────────────────────────────────
    recent_actions = (state.get("v30_phase_recent_actions") or {}).get(pid, [])
    args_hash = _hash_action(tool_name, tool_args)
    is_stuck = sum(
        1 for a in recent_actions[-STUCK_DETECTOR_WINDOW:]
        if a.get("tool") == tool_name and a.get("args_hash") == args_hash
    ) >= STUCK_DETECTOR_WINDOW

    if is_stuck:
        logger.warning(
            "agentic_phase_loop: phase %s stuck (same %s for %d rounds) — escalate",
            pid, tool_name, STUCK_DETECTOR_WINDOW + 1,
        )
        return {
            "status": "phase_revise_pending",
            "sse_events": [_event("phase_revise_started", {
                "phase_id": pid, "reason": "stuck_repeat_action",
                "tool": tool_name,
            })],
        }

    # ── Dispatch tool ─────────────────────────────────────────────────
    action_result: dict[str, Any]
    try:
        method = getattr(toolset, tool_name, None)
        if method is None or not callable(method):
            raise ToolError(code="UNKNOWN_TOOL", message=f"No tool {tool_name}")
        action_result = await method(**tool_args)
    except ToolError as e:
        logger.info("agentic_phase_loop: tool %s failed: %s", tool_name, e.message)
        action_result = {"error": e.message, "code": e.code, "hint": e.hint}
    except Exception as e:  # noqa: BLE001
        logger.warning("agentic_phase_loop: tool %s threw: %s", tool_name, e)
        action_result = {"error": f"{type(e).__name__}: {e}"}

    # ── Auto-preview after canvas-mutating tools ─────────────────────
    # v30.1 (2026-05-16): preview output is now handed off to
    # phase_spanning_verifier_node (next graph node) via state.v30_last_preview
    # so it can extract concrete outcome values (ooc_count, n_series, etc.)
    # for the fast-forward report. exec_trace mirror is also written so the
    # verifier — and the next round's observation prompt — see the runtime
    # schema for the new node.
    auto_preview_result = None
    auto_preview_blob = None
    last_mutated_logical_id: str | None = None
    snapshot_dict = None
    mutating = {"add_node", "set_param", "connect", "remove_node"}
    if tool_name in mutating and "error" not in action_result:
        target_nid = action_result.get("node_id") or tool_args.get("node_id") or tool_args.get("to_node")
        if target_nid:
            try:
                pv = await toolset.preview(node_id=target_nid, sample_size=5)
                auto_preview_result = {
                    "node_id": target_nid,
                    "rows": pv.get("rows"),
                    "status": pv.get("status"),
                }
                auto_preview_blob = pv.get("preview") or {}
                # Build exec_trace snapshot for verifier + next round prompt.
                # logical_id == real_id in v30 (toolset returns real id from
                # add_node; we don't maintain a separate logical map here).
                last_mutated_logical_id = target_nid
                # Find block_id for this real id from current pipeline
                blk_id = None
                for n in transient.pipeline_json.nodes:
                    if n.id == target_nid:
                        blk_id = n.block_id
                        break
                # Extract simple sample row + columns from preview (mirrors
                # execute._snapshot_node behaviour for v27 compat).
                cols: list[str] = []
                sample = None
                for _port, blob in (auto_preview_blob or {}).items():
                    if not isinstance(blob, dict):
                        continue
                    if blob.get("type") == "dataframe":
                        cols = list(blob.get("columns") or [])
                        rs = (
                            blob.get("sample_rows") or blob.get("rows_sample")
                            or blob.get("rows") or []
                        )
                        if rs and isinstance(rs[0], dict):
                            sample = rs[0]
                        break
                    if blob.get("type") in ("dict", "chart_spec"):
                        snap = blob.get("snapshot") or blob
                        if isinstance(snap, dict):
                            sample = {k: snap[k] for k in list(snap.keys())[:6]}
                        break
                # v30.4 (2026-05-16): populate runtime_schema_md the same
                # way execute._snapshot_node does. Without it, observation_md
                # falls back to bare `cols=[...]` and LLM loses column_docs
                # usage hints (e.g. "use spc_summary.ooc_count to skip
                # unnest+filter+count 4 steps"). That regression caused
                # Run 1 to walk the long path instead of the shortcut.
                runtime_schema_md = ""
                try:
                    from python_ai_sidecar.agent_builder.graph_build.nodes.execute import (
                        _build_runtime_schema_md,
                    )
                    runtime_schema_md = _build_runtime_schema_md(
                        block_id=blk_id or "",
                        logical_id=target_nid,
                        cols=cols,
                        rows_sample=auto_preview_blob,
                        toolset=toolset,
                        total_rows=pv.get("rows"),
                    )
                except Exception as ex:  # noqa: BLE001
                    logger.info("runtime_schema_md build failed (non-fatal): %s", ex)
                snapshot_dict = {
                    "logical_id": target_nid,
                    "real_id": target_nid,
                    "block_id": blk_id,
                    "rows": pv.get("rows"),
                    "cols": cols[:20],
                    "sample": sample,
                    "runtime_schema_md": runtime_schema_md,
                    "error": pv.get("error"),
                    "after_cursor": round_n,
                }
            except Exception as ex:  # noqa: BLE001
                logger.info("auto-preview %s failed: %s", target_nid, ex)

    # ── Build state update + SSE ──────────────────────────────────────
    new_pipeline_dict = transient.pipeline_json.model_dump(by_alias=True)
    new_recent = dict(state.get("v30_phase_recent_actions") or {})
    # v30 hotfix: store result digest too so next round's prompt can show
    # LLM what it already learned (LLM has no memory across rounds — each
    # round is a fresh call). Without this LLM keeps re-inspecting same
    # block because it forgot the doc it already pulled.
    result_digest = _make_result_digest(tool_name, action_result)
    new_recent[pid] = recent_actions[-(STUCK_DETECTOR_WINDOW * 2):] + [{
        "tool": tool_name,
        "args_hash": args_hash,
        "args_summary": _summarize_args(tool_args),
        "result_digest": result_digest,
    }]

    # v30 C-A2: append assistant(tool_use) + user(tool_result + fresh obs diff)
    # to preserve conversation continuity. MUST run before state_update
    # since state_update references new_msgs.
    if assistant_content:
        phase_messages.append({"role": "assistant", "content": assistant_content})
    if tool_use_id:
        result_digest_text = _make_result_digest(tool_name, action_result)
        # v30.17l hotfix: pass state so canvas_diff_md can include
        # VERIFIER FEEDBACK on follow-up rounds (was only in initial obs_md).
        canvas_diff_text = _build_canvas_diff_md(transient.pipeline_json, phase, state)
        phase_messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id,
                 "content": result_digest_text},
                {"type": "text", "text": canvas_diff_text},
            ],
        })
    # Cap message stack to avoid runaway token use (~16 round-trips).
    if len(phase_messages) > 32:
        phase_messages = phase_messages[-32:]
    new_msgs = dict(state.get("v30_phase_messages") or {})
    new_msgs[pid] = phase_messages

    state_update: dict[str, Any] = {
        "v30_phase_round": round_n + 1,
        "v30_phase_recent_actions": new_recent,
        "v30_phase_messages": new_msgs,
        "final_pipeline": new_pipeline_dict,
    }

    # v30.1 (2026-05-16): hand off mutation snapshot to phase_verifier_node.
    # Verifier reads these to decide phase advancement + extract outcome
    # values for the fast-forward report. None for inspect-only rounds.
    if last_mutated_logical_id and snapshot_dict:
        new_exec_trace = dict(state.get("exec_trace") or {})
        new_exec_trace[last_mutated_logical_id] = snapshot_dict
        state_update["exec_trace"] = new_exec_trace
        state_update["v30_last_mutated_logical_id"] = last_mutated_logical_id
        state_update["v30_last_preview"] = auto_preview_blob
    else:
        # Explicit clear so verifier no-ops on inspect-only / errored rounds.
        state_update["v30_last_mutated_logical_id"] = None
        state_update["v30_last_preview"] = None

    # Pipeline snapshot for frontend canvas re-render after canvas-mutating
    # actions. Cheap (just dump model). Skip for inspect_* / phase_complete.
    pipeline_snapshot = None
    if tool_name in mutating:
        pipeline_snapshot = new_pipeline_dict

    sse_events = [
        _event("phase_round", {
            "phase_id": pid, "round": round_n + 1, "max": MAX_REACT_ROUNDS,
        }),
        _event("phase_action", {
            "phase_id": pid, "round": round_n + 1,
            "tool": tool_name,
            "args_summary": _summarize_args(tool_args),
            "result_summary": _summarize_result(action_result),
            "pipeline_snapshot": pipeline_snapshot,
            # v30.17h (2026-05-17) — raw structured args/result needed by
            # the frontend Lite Canvas. Without these wrap_build_event_for_chat
            # only had text summaries → applyGlassOp couldn't extract
            # block_name / node_id → canvas stayed empty. Keep the *_summary
            # text fields too (chat log still uses them).
            "tool_args_raw": tool_args,
            "action_result_raw": action_result,
        }),
    ]
    if auto_preview_result:
        sse_events.append(_event("phase_observation", {
            "phase_id": pid, "round": round_n + 1,
            "preview": auto_preview_result,
        }))

    if tracer is not None:
        tracer.record_step(
            "agentic_phase_loop", status="round_done",
            phase_id=pid, round=round_n + 1,
            tool=tool_name,
            action_ok="error" not in action_result,
            auto_preview=auto_preview_result,
            mutated_node=last_mutated_logical_id,
        )

    state_update["sse_events"] = sse_events
    return state_update


async def step_pause_gate_node(state: BuildGraphState) -> dict[str, Any]:
    """v30.7 (2026-05-16): debug step-mode pause point.

    Runs between phase_verifier and next agentic_phase_loop round when
    state.debug_step_mode is True. Emits a `phase_round_paused` SSE event
    with the full diagnostic payload (system prompt, user_msg sent to LLM
    this round, LLM response, tool result, verifier outcome, canvas state),
    then interrupt()s the graph. Resume via POST /agent/build/step-continue
    with body {sessionId, action: "continue" | "abort"}.

    Falls through (no-op) when debug_step_mode is False so the gate is
    cheap to leave permanently in the graph.
    """
    if not state.get("debug_step_mode"):
        return {}

    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    round_n = state.get("v30_phase_round", 0)
    phase = phases[idx] if 0 <= idx < len(phases) else None
    pid = (phase or {}).get("id") if phase else None

    # Reconstruct what LLM saw + said this round, from state.
    phase_messages = (state.get("v30_phase_messages") or {}).get(pid or "", [])
    last_user_msg = ""
    last_assistant_content: list[dict] = []
    for m in phase_messages:
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                last_user_msg = c
            elif isinstance(c, list):
                parts = []
                for p in c:
                    if isinstance(p, dict):
                        if p.get("type") == "text":
                            parts.append(p.get("text") or "")
                        elif p.get("type") == "tool_result":
                            parts.append(
                                f"[tool_result: {str(p.get('content',''))[:300]}]"
                            )
                last_user_msg = "\n".join(parts)
        elif m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, list):
                last_assistant_content = c

    # Recent actions (this phase) for context
    recent = (state.get("v30_phase_recent_actions") or {}).get(pid or "", [])

    pause_payload = {
        "kind": "phase_round_paused",
        "session_id": state.get("session_id"),
        "phase_id": pid,
        "phase_goal": (phase or {}).get("goal"),
        "phase_expected": (phase or {}).get("expected"),
        "round": round_n,                    # round that just completed
        "max_rounds": MAX_REACT_ROUNDS,
        "current_phase_idx": idx,
        "n_phases": len(phases),
        "system_prompt": _SYSTEM,
        "user_msg_last_round": last_user_msg,
        "assistant_content_last_round": last_assistant_content,
        "recent_actions": recent[-6:] if recent else [],
        "canvas_snapshot": state.get("final_pipeline"),
        "exec_trace_keys": list((state.get("exec_trace") or {}).keys()),
        "last_mutated_logical_id": state.get("v30_last_mutated_logical_id"),
    }

    logger.info(
        "step_pause_gate: pausing at phase=%s round=%d (debug_step_mode)",
        pid, round_n,
    )

    user_response = interrupt(pause_payload)

    if not isinstance(user_response, dict):
        user_response = {"action": "continue"}
    action = str(user_response.get("action") or "continue")

    if action == "abort":
        logger.info("step_pause_gate: user aborted at phase=%s round=%d", pid, round_n)
        return {
            "status": "cancelled",
            "summary": "User aborted via debug step mode",
            "v30_step_paused_at_round": None,
            "sse_events": [{
                "event": "step_aborted",
                "data": {"phase_id": pid, "round": round_n},
            }],
        }

    # action == "continue" (default) — just clear paused marker, fall through
    return {
        "v30_step_paused_at_round": None,
        "sse_events": [{
            "event": "step_resumed",
            "data": {"phase_id": pid, "round": round_n},
        }],
    }


def _build_catalog_brief() -> str:
    """v30 hotfix: LLM has no idea which blocks exist unless we list them.
    Dump all block names + category + 1-line `what` so the LLM can pick
    a real block_id to add_node OR inspect_block_doc.

    Cached after first build per-process (catalog is constant).
    """
    global _CATALOG_BRIEF_CACHE
    if _CATALOG_BRIEF_CACHE is not None:
        return _CATALOG_BRIEF_CACHE

    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    import re
    registry = SeedlessBlockRegistry()
    registry.load()

    by_category: dict[str, list[str]] = {}
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        cat = spec.get("category") or "transform"
        desc = (spec.get("description") or "").strip()
        # Extract first non-empty line of `== What ==` section as 1-line summary
        what_line = ""
        m = re.search(r"== What ==\s*\n+(.+?)(?:\n\n|\n==)", desc, re.DOTALL)
        if m:
            first = m.group(1).strip().split("\n")[0]
            what_line = first[:90]
        else:
            # fallback: first line of desc
            what_line = desc.split("\n", 1)[0][:90]
        by_category.setdefault(cat, []).append(f"  {name}  -- {what_line}")

    lines: list[str] = []
    for cat in sorted(by_category.keys()):
        lines.append(f"[{cat}]")
        for entry in sorted(by_category[cat]):
            lines.append(entry)
        lines.append("")

    _CATALOG_BRIEF_CACHE = "\n".join(lines)
    return _CATALOG_BRIEF_CACHE


_CATALOG_BRIEF_CACHE: str | None = None


# v30.2 (2026-05-16): cap how many composite candidates to list. More than
# 3 dilutes the signal; 1 alone risks looking like a recommendation rather
# than an enumeration.
_ONEBLOCK_MAX_CANDIDATES = 3


def _build_oneblock_solutions_section(
    current_phase: dict, remaining_phases: list[dict],
) -> str:
    """Compute server-detected 1-block solutions for current + remaining
    phases. Returns the rendered SOLUTIONS section, or empty string when
    no composite block has fast-forward potential.

    A "solution" is a block whose `produces.covers` includes
    current_phase.expected AND at least one remaining phase's expected
    (so the LLM actually saves rounds by picking it).

    Validated via tools/trace_replay (2026-05-16, EQP-08 p1 r1):
      identity / enrich_catalog_brief / rewrite_phase_goal_generic:
        3/3 picks = block_process_history (no shift)
      THIS section prepended: 3/3 picks = block_spc_panel

    LLM literally cites the section text in its reasoning.
    """
    from python_ai_sidecar.pipeline_builder.seedless_registry import (
        SeedlessBlockRegistry,
    )
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _resolve_covers,
    )

    cur_expected = (current_phase.get("expected") or "").strip()
    if not cur_expected:
        return ""

    registry = SeedlessBlockRegistry()
    registry.load()

    # solutions: (block_name, contiguous_ff_ids, all_covered_future_ids,
    #             output_covers, internal_extras)
    # v30.5: use covers_output (output port semantics — same as verifier).
    # v30.6: also list COMPOSITE blocks (covers_internal > covers_output)
    # even without FF benefit, so LLM at the right output phase still sees
    # the composite annotation (e.g. spc_panel at chart phase: "this also
    # internally does raw_data + transform + verdict").
    solutions: list[tuple[str, list[str], list[str], list[str], list[str]]] = []
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        output_covers = _resolve_covers(spec, kind="output")
        if cur_expected not in output_covers:
            continue

        internal_covers = _resolve_covers(spec, kind="internal")
        internal_extras = sorted(set(internal_covers) - set(output_covers))
        is_composite = bool(internal_extras)

        # Contiguous chain — what verifier will actually fast-forward
        ff_ids: list[str] = []
        for nxt in remaining_phases:
            nxt_exp = (nxt.get("expected") or "").strip()
            if nxt_exp and nxt_exp in output_covers:
                ff_ids.append(nxt.get("id"))
            else:
                break  # contiguous-only chain (matches verifier semantics)

        # Non-contiguous coverage — what this block COULD eventually satisfy
        # in later phases, even if a non-covered phase intervenes.
        future_covered = [
            nxt.get("id") for nxt in remaining_phases
            if (nxt.get("expected") or "").strip() in output_covers
        ]

        # v30.7 (2026-05-16): tightened promotion. Only include if:
        #   (a) has contiguous FF chain (real verifier benefit), OR
        #   (b) is composite with internal_extras (covers_internal > output)
        # Non-contig future_covered alone is too noisy — promoted generic
        # transform blocks (any_trigger / apc_long_form / compute) just
        # because some future phase also = transform, with no actual help
        # for the current task. EQP-08 p2 trace confirmed this noise.
        if ff_ids or is_composite:
            solutions.append((name, ff_ids, future_covered, output_covers, internal_extras))

    if not solutions:
        return ""

    # Sort: bigger contiguous FF first, then more future-covered, then
    # composite (more internal_extras), then name.
    solutions.sort(key=lambda t: (-len(t[1]), -len(t[2]), -len(t[4]), t[0]))
    cur_id = current_phase.get("id") or "current"
    out_lines = [
        "== 1-BLOCK SOLUTIONS (server-detected; verifier-confirmed) ==",
        "Server 比對 phase.expected 與 block.produces.covers_output 算出（事實，非建議）。",
        "**優先評估這些 candidate**：composite block 即使只滿足當前 phase，也常常一個 block 取代多步拼湊。",
    ]
    for name, ff_ids, future_covered, output_covers, internal_extras in solutions[:_ONEBLOCK_MAX_CANDIDATES]:
        chain = f"{cur_id}" + ("".join(f"+{i}" for i in ff_ids) if ff_ids else "")
        n_chain = len(ff_ids) + 1

        # Compose annotations: FF, non-contig coverage, composite internal work
        annotations: list[str] = []
        if ff_ids:
            annotations.append(f"fast-forward {chain} ({n_chain} phases auto-advance)")
        beyond = [pid for pid in future_covered if pid not in ff_ids]
        if beyond:
            annotations.append(f"also covers later {'+'.join(beyond)} (reusable then)")
        if internal_extras:
            annotations.append(
                f"composite — internally also does work of "
                f"[{'+'.join(internal_extras)}] (取代上游多步拼湊)"
            )
        if not annotations:
            annotations.append(f"satisfies {cur_id} ({cur_expected})")

        out_lines.append(
            f"  {name}  → " + "; ".join(annotations)
            + f"  [output={'+'.join(output_covers)}]"
        )
    out_lines.append(
        "若這些都不適用（user 要求的細節超過 composite 的能力），"
        "再走逐 phase 拼 transform/filter/chart 的傳統路徑。"
    )
    return "\n".join(out_lines)


def _build_canvas_diff_md(pipeline: PipelineJSON, phase: dict, state: dict | None = None) -> str:
    """Compact canvas snapshot for the post-action user message.

    Only shows current node IDs + block_ids + edges, plus a reminder of
    the phase goal. The full observation_md is only sent on round 1; on
    subsequent rounds this lighter diff keeps token use down.

    v30.17l hotfix: also include VERIFIER FEEDBACK if the previous round's
    block was rejected. Without this the LLM only sees the feedback on
    round 1 of a phase, then forgets — and reject events happen on round
    2+ when blocks first get verifier-checked.
    """
    lines: list[str] = []

    # v30.17l: VERIFIER FEEDBACK first (before canvas) so LLM sees rejection
    # before re-reading canvas state.
    if state:
        vr = state.get("v30_last_verifier_reject")
        if vr and isinstance(vr, dict):
            block = vr.get("block_id") or "(unknown)"
            cov = vr.get("covers") or []
            exp = vr.get("expected") or ""
            result = vr.get("result") or "no_match"
            wp = vr.get("would_have_passed_with") or []
            lines.append("== VERIFIER FEEDBACK (your last block was rejected) ==")
            lines.append(f"  rejected: {block} (covers={cov})")
            lines.append(f"  this phase expects: {exp}")
            lines.append(f"  reason: {result}")
            if result == "covers mismatch":
                lines.append(
                    f"  → '{exp}' is not in the rejected block's covers. "
                    f"You MUST pick a different block."
                )
            elif result == "llm_judge_rejected":
                jrr = (vr.get("judge_reject_reason") or "")[:140]
                lines.append(f"  → semantic check failed: {jrr}")
            if wp:
                lines.append(f"  blocks that WOULD pass: {wp[:8]}")
                lines.append("  → switch to one of these; don't retry the rejected block.")
            lines.append("")

    lines.append(
        f"== CANVAS NOW ({len(pipeline.nodes)} nodes, {len(pipeline.edges)} edges) =="
    )
    for n in pipeline.nodes[:20]:
        params_short = ", ".join(f"{k}={v!r}"[:40] for k, v in (n.params or {}).items())[:120]
        lines.append(f"  {n.id} [{n.block_id}]  params={{{params_short}}}")
    for e in pipeline.edges[:20]:
        lines.append(f"  edge {e.from_.node}->{e.to.node}")
    lines.append("")

    # v30.12 (2026-05-17) — matched-only CONNECT OPTIONS view.
    # For each node with un-connected input ports, list type-compatible
    # source ports (or [NO COMPATIBLE SOURCE] + producer block hints).
    # Validated via trace_replay: 3/3 picks correct architecture vs 0/3
    # baseline. See docs/RAG migration roadmap for the future on-demand
    # replacement (project_rag_for_llm_lookups.md).
    co_section = _build_connect_options_md(pipeline)
    if co_section:
        lines.append(co_section)
        lines.append("")

    lines.append(f"PHASE GOAL: {phase.get('goal')} (expected: {phase.get('expected')})")
    lines.append("Pick your next single tool call.")
    return "\n".join(lines)


def _types_compatible(src_type: str | None, dst_type: str | None) -> bool:
    if not src_type or not dst_type:
        return True  # unknown — permissive
    if src_type == dst_type:
        return True
    if "any" in (src_type, dst_type):
        return True
    return False


def _build_connect_options_md(pipeline: PipelineJSON) -> str:
    """Emit `== CONNECT OPTIONS for nX ==` sections for nodes with un-filled
    input ports. For each unfilled input, list type-compatible source ports
    across ALL existing nodes (allows fan-out). If no compatible source,
    list blocks that DO produce the needed type.
    """
    if not pipeline.nodes:
        return ""

    registry = SeedlessBlockRegistry()
    registry.load()

    def _spec(block_id: str) -> dict:
        return registry.get_spec(block_id, "1.0.0") or {}

    # Build per-node port info
    node_info: dict[str, dict] = {}
    for n in pipeline.nodes:
        spec = _spec(n.block_id)
        node_info[n.id] = {
            "id": n.id,
            "block_id": n.block_id,
            "in_ports": list(spec.get("input_schema") or []),
            "out_ports": list(spec.get("output_schema") or []),
        }

    # Track which (node, in_port) pairs already have incoming edges
    filled: set[tuple[str, str]] = set()
    for e in pipeline.edges:
        filled.add((e.to.node, e.to.port))

    sections: list[str] = []
    for n_id, n in node_info.items():
        in_ports = n["in_ports"]
        if not in_ports:
            continue
        unfilled = [p for p in in_ports if (n_id, p.get("port")) not in filled]
        if not unfilled:
            continue

        sec = [f"== CONNECT OPTIONS for {n_id} ({n['block_id']}) =="]
        for in_port in unfilled:
            iname, itype = in_port.get("port"), in_port.get("type")
            sec.append(f"{n_id}.{iname} ({itype}):")

            compats: list[tuple[str, str, str, str]] = []
            for src_id, src in node_info.items():
                if src_id == n_id:
                    continue
                for op in src["out_ports"]:
                    if _types_compatible(op.get("type"), itype):
                        compats.append((src_id, src["block_id"], op.get("port") or "?", op.get("type") or "?"))

            if compats:
                sec.append("  Compatible sources (pick semantically; fan-out OK):")
                for sid, sblock, sport, stype in compats:
                    sec.append(f"    {sid}.{sport}   [{sblock}]  ({stype})")
            else:
                producers = _find_blocks_producing_type(registry, itype)
                sec.append("  [NO COMPATIBLE SOURCE in current pipeline]")
                if producers:
                    ps = ", ".join(producers[:8])
                    sec.append(
                        f"  Need to add an intermediate block first. "
                        f"Blocks that output type={itype}: {ps}"
                    )
                else:
                    sec.append(f"  No registered block outputs type={itype}.")

        sections.append("\n".join(sec))

    return "\n\n".join(sections)


def _find_blocks_producing_type(registry: SeedlessBlockRegistry, target_type: str | None) -> list[str]:
    if not target_type:
        return []
    out: list[str] = []
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        for op in spec.get("output_schema") or []:
            if _types_compatible(op.get("type"), target_type):
                out.append(name)
                break
    return sorted(out)


def _build_observation_md(state: BuildGraphState, phase: dict) -> str:
    """Assemble the prompt user content for current round."""
    lines: list[str] = []

    # v30.2 (2026-05-16): TOP-of-prompt 1-block solutions section.
    # When a composite block (covers >= 2 phase kinds, with at least one
    # remaining phase also covered) can satisfy current + next N phases,
    # surface it here BEFORE the phase goal text. Validated via
    # tools/trace_replay 3-rep A/B: only this placement (vs catalog-brief
    # enrichment or goal-text rewrite) actually shifts LLM picks.
    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
    one_block_section = _build_oneblock_solutions_section(phase, phases[idx + 1:])
    if one_block_section:
        lines.append(one_block_section)
        lines.append("")

    # v30.10 B2: previous phases' actual outcomes (LLM-judge confirmed).
    # Shows LLM what each completed phase REALLY produced + which node is
    # the official upstream, avoiding re-derivation from canvas state.
    outcomes = state.get("v30_phase_outcomes") or {}
    completed = [
        (p, outcomes[p["id"]]) for p in phases[:idx]
        if outcomes.get(p["id"], {}).get("status") == "completed"
    ]
    if completed:
        lines.append("== COMPLETED PHASES (per plan + actual, LLM-judge confirmed) ==")
        for p, oc in completed:
            target = (p.get("expected_output") or {}).get("value_desc") or "(no target spec)"
            block = oc.get("advanced_by_block") or "?"
            node = oc.get("advanced_by_node") or "?"
            summary = oc.get("llm_summary") or oc.get("rationale") or ""
            extracted = oc.get("llm_extracted") or {}
            ex_str = ""
            if extracted:
                ex_parts = [f"{k}={v}" for k, v in list(extracted.items())[:4] if v is not None]
                if ex_parts:
                    ex_str = "  " + ", ".join(ex_parts)
            lines.append(
                f"  {p['id']}: target={target[:80]}"
            )
            lines.append(
                f"      → {node} [{block}]  {summary[:120]}{ex_str}"
            )
        lines.append("")

    # Phase goal (user-confirmed — must follow)
    lines.append("== CURRENT PHASE (user-confirmed; do not deviate) ==")
    lines.append(f"id: {phase.get('id')}")
    lines.append(f"goal: {phase.get('goal')}")
    lines.append(f"expected: {phase.get('expected')}")
    if phase.get("why"):
        lines.append(f"why: {phase.get('why')}")
    lines.append("")

    # v30.10 B2: surface last LLM-judge reject reason so LLM knows what's
    # missing to actually complete the phase (rather than re-trying same path)
    judge_reject = state.get("v30_last_judge_reject_reason")
    if judge_reject:
        lines.append("⚠ VERIFIER LLM-JUDGE rejected previous attempt:")
        lines.append(f"   {judge_reject}")
        lines.append("   → 修正 pipeline 補完 phase goal 才能 advance")
        lines.append("")

    # v30.17l (2026-05-18) — surface full verifier reject info so LLM doesn't
    # keep retrying the same wrong block. Includes the rejected block_id,
    # specific failure mode (covers mismatch / rows gate / judge), and the
    # actual blocks that WOULD satisfy this phase.
    vr = state.get("v30_last_verifier_reject")
    if vr and isinstance(vr, dict):
        result = vr.get("result") or "no_match"
        block = vr.get("block_id") or "(unknown)"
        cov = vr.get("covers") or []
        exp = vr.get("expected") or ""
        wp = vr.get("would_have_passed_with") or []
        lines.append("== VERIFIER FEEDBACK (last attempt rejected) ==")
        lines.append(f"  rejected block: {block}  (covers={cov})")
        lines.append(f"  phase expects: {exp}")
        lines.append(f"  reason: {result}")
        if result == "covers mismatch":
            lines.append(
                f"  → '{exp}' is not in the rejected block's covers. "
                f"You MUST pick a different block."
            )
        elif result == "rows quality gate failed":
            lines.append(
                f"  → block ran but produced rows={vr.get('rows')}. "
                f"Fix upstream params or pick a block that yields data."
            )
        elif result == "llm_judge_rejected":
            lines.append(
                f"  → semantic check failed: {vr.get('judge_reject_reason','')[:120]}"
            )
        if wp:
            lines.append(f"  blocks that WOULD pass for expected={exp}: {wp[:8]}")
            lines.append("  → switch to one of these. Don't retry the rejected block.")
        lines.append("")

    # All phases context
    lines.append("== ALL PHASES CONTEXT ==")
    for i, p in enumerate(phases):
        marker = " <-- you are here" if i == idx else ""
        lines.append(f"  {p['id']}: {p['goal']} (expected: {p['expected']}){marker}")
    lines.append("")

    # AVAILABLE INPUTS section
    lines.append("== AVAILABLE INPUTS ==")
    base_pipeline = state.get("base_pipeline") or {}
    declared = base_pipeline.get("inputs") or []
    if declared:
        lines.append("Pipeline declared inputs:")
        for inp in declared:
            if isinstance(inp, dict) and inp.get("name"):
                lines.append(f"  ${inp['name']} ({inp.get('type','string')}) — {inp.get('description','')}")
    else:
        lines.append("(no pipeline-level inputs declared)")
    lines.append("")

    # Canvas snapshot — runtime schemas
    exec_trace = state.get("exec_trace") or {}
    lines.append("Canvas nodes (with runtime schema):")
    if not exec_trace:
        lines.append("  (empty canvas — no nodes built yet)")
    else:
        for lid, snap in exec_trace.items():
            if not isinstance(snap, dict):
                continue
            md = snap.get("runtime_schema_md") or ""
            if md:
                lines.append(md)
                lines.append("")
            else:
                # fallback for v27 snapshots without schema md
                lines.append(f"  {lid} [{snap.get('block_id')}] rows={snap.get('rows')} cols={snap.get('cols', [])[:10]}")
    lines.append("")

    # v30.12 (2026-05-17) — same matched-only CONNECT OPTIONS view as
    # _build_canvas_diff_md uses post-action. Surfaces here on round 1 of
    # later phases (canvas may already have prior phases' nodes with
    # un-connected input ports — e.g. p5 alarm node with no Logic Node yet).
    pj_dict = state.get("final_pipeline") or state.get("base_pipeline")
    if pj_dict:
        try:
            pj = PipelineJSON.model_validate(pj_dict)
            co_md = _build_connect_options_md(pj)
            if co_md:
                lines.append(co_md)
                lines.append("")
        except Exception:  # noqa: BLE001 — schema variations across v27/v30 paths
            pass

    # Action history this phase — INCLUDE result digest so LLM has memory
    # of what it learned. Without this each round is amnesic and LLM
    # re-inspects same blocks endlessly.
    pid = phase.get("id")
    recent = (state.get("v30_phase_recent_actions") or {}).get(pid, [])
    if recent:
        lines.append("== ACTIONS THIS PHASE — what you did + what you got back ==")
        for a in recent[-6:]:
            tool = a.get("tool")
            args = a.get("args_summary", "")
            digest = a.get("result_digest", "")
            lines.append(f"  - {tool}({args})")
            lines.append(f"    -> {digest}")
        lines.append(
            "IMPORTANT: do NOT repeat the same tool with same args. "
            "If you already inspected a block_doc, USE the info to add_node — do not inspect again."
        )
        lines.append("")

    # Instruction
    instr = state.get("instruction") or ""
    if instr:
        lines.append("== USER INSTRUCTION (for context) ==")
        lines.append(instr[:600])
        lines.append("")

    # AVAILABLE BLOCKS catalog (must be present so LLM picks real block_id)
    lines.append("== AVAILABLE BLOCKS (you MUST pick a block_id from this list) ==")
    lines.append(_build_catalog_brief())
    lines.append(
        "When you call add_node, block_name MUST exactly match a name above. "
        "If unsure how to use a block, call inspect_block_doc(block_id) first."
    )
    lines.append("")

    lines.append("== YOUR NEXT ACTION (single tool call) ==")
    lines.append("Pick ONE tool to advance toward the phase goal.")
    return "\n".join(lines)


def _build_tool_specs() -> list[dict[str, Any]]:
    """Anthropic tool-use schema for v30 tools."""
    return [
        {
            "name": "inspect_node_output",
            "description": "Read an existing node's actual output (cols + up to 3 sample rows).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "n_rows": {"type": "integer", "minimum": 1, "maximum": 3, "default": 2},
                },
                "required": ["node_id"],
            },
        },
        {
            "name": "inspect_block_doc",
            "description": "Get full doc for a block (description + param_schema + column_docs + examples).",
            "input_schema": {
                "type": "object",
                "properties": {"block_id": {"type": "string"}},
                "required": ["block_id"],
            },
        },
        {
            "name": "add_node",
            "description": "Add a node to the pipeline canvas.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "block_name": {"type": "string"},
                    "block_version": {"type": "string", "default": "1.0.0"},
                    "params": {"type": "object"},
                },
                "required": ["block_name"],
            },
        },
        {
            "name": "connect",
            "description": "Connect two nodes' ports.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "from_node": {"type": "string"},
                    "from_port": {"type": "string", "default": "data"},
                    "to_node": {"type": "string"},
                    "to_port": {"type": "string", "default": "data"},
                },
                "required": ["from_node", "to_node"],
            },
        },
        {
            "name": "set_param",
            "description": "Modify a node's param.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string"},
                    "key": {"type": "string"},
                    "value": {},
                },
                "required": ["node_id", "key", "value"],
            },
        },
        {
            "name": "remove_node",
            "description": "Remove a node + its edges.",
            "input_schema": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        },
        {
            "name": "phase_complete",
            "description": "Declare current phase done — verifier checks; if mismatch, you must continue rounds.",
            "input_schema": {
                "type": "object",
                "properties": {"rationale": {"type": "string"}},
                "required": ["rationale"],
            },
        },
    ]


def _extract_tool_call(resp: Any) -> dict[str, Any] | None:
    """Extract first tool_use block from LLM response. Returns None if none.
    Returns {name, args, id} where id is the tool_use_id needed for the
    matching tool_result in the next user message.
    """
    content = getattr(resp, "content", None) or []
    if not isinstance(content, list):
        return None
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype == "tool_use":
            name = getattr(blk, "name", None) or (blk.get("name") if isinstance(blk, dict) else None)
            args = getattr(blk, "input", None) or (blk.get("input") if isinstance(blk, dict) else None) or {}
            tu_id = getattr(blk, "id", None) or (blk.get("id") if isinstance(blk, dict) else None)
            if name:
                return {
                    "name": name,
                    "args": dict(args) if isinstance(args, dict) else {},
                    "id": tu_id,
                }
    return None


def _extract_assistant_content(resp: Any) -> list[dict] | None:
    """Convert Anthropic response.content (list of TextBlock | ToolUseBlock)
    into the dict shape needed for `messages` history when sending it back
    in the next request.
    """
    content = getattr(resp, "content", None) or []
    if not isinstance(content, list):
        return None
    out: list[dict] = []
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype == "text":
            text = getattr(blk, "text", None) or (blk.get("text") if isinstance(blk, dict) else None)
            if text:
                out.append({"type": "text", "text": str(text)})
        elif btype == "tool_use":
            name = getattr(blk, "name", None) or (blk.get("name") if isinstance(blk, dict) else None)
            args = getattr(blk, "input", None) or (blk.get("input") if isinstance(blk, dict) else None) or {}
            tu_id = getattr(blk, "id", None) or (blk.get("id") if isinstance(blk, dict) else None)
            if name and tu_id:
                out.append({
                    "type": "tool_use",
                    "id": tu_id,
                    "name": name,
                    "input": args if isinstance(args, dict) else {},
                })
    return out or None


def _hash_action(tool: str, args: dict) -> str:
    blob = json.dumps({"t": tool, "a": args}, sort_keys=True, default=str)
    return hashlib.md5(blob.encode()).hexdigest()[:12]


def _summarize_args(args: dict) -> str:
    if not args:
        return ""
    parts = [f"{k}={_short_repr(v)}" for k, v in list(args.items())[:4]]
    return ", ".join(parts)


def _summarize_result(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)[:80]
    if "error" in result:
        return f"error: {str(result.get('error'))[:80]}"
    if "node_id" in result:
        return f"node_id={result['node_id']}"
    if result.get("phase_complete_signal"):
        return "phase_complete signaled"
    return str(result)[:80]


def _short_repr(v: Any) -> str:
    s = repr(v) if not isinstance(v, str) else v
    return s[:60] + ("..." if len(s) > 60 else "")


def _make_result_digest(tool: str, result: Any) -> str:
    """Compact summary of what a tool returned, for showing back to LLM
    in next round so it doesn't forget what it already learned."""
    if not isinstance(result, dict):
        return str(result)[:100]
    # Only treat as error when the error field is non-None.
    # Previously `"error" in result` matched even when value was None,
    # making LLM think "ERROR: None" everywhere.
    err_val = result.get("error")
    if err_val is not None and err_val != "":
        return f"ERROR: {str(err_val)[:120]}"
    if tool == "inspect_block_doc":
        # Show enough to add_node correctly: REQUIRED params (verbatim names!),
        # param-schema enum hints, and examples count. Without this LLM keeps
        # using synonyms (equipment_id instead of tool_id, etc.).
        bid = result.get("block_id")
        cat = result.get("category")
        ps = result.get("param_schema") or {}
        required = ps.get("required") or []
        props = ps.get("properties") or {}
        param_lines = []
        for pname, pspec in list(props.items())[:12]:
            ptype = pspec.get("type", "?")
            req = "REQUIRED" if pname in required else "opt"
            default = pspec.get("default")
            enum = pspec.get("enum")
            extra = ""
            if default is not None: extra += f" default={default!r}"
            if enum: extra += f" enum={enum}"
            param_lines.append(f"    {pname} ({ptype}, {req}){extra}")
        ex = result.get("examples") or []
        ex_lines = []
        for e in ex[:2]:
            label = e.get("label", "")
            params = e.get("params", {})
            ex_lines.append(f"    {label}: params={params}")
        return (
            f"got block_doc for {bid} (cat={cat}). USE THESE EXACT param names:\n"
            + "\n".join(param_lines)
            + (f"\n  EXAMPLES:\n" + "\n".join(ex_lines) if ex_lines else "")
            + "\n  -- you now know enough to add_node. DO NOT re-inspect this block."
        )
    if tool == "inspect_node_output":
        nid = result.get("node_id")
        rows = result.get("rows")
        ports = [k for k in result if k not in {"node_id", "status", "rows", "error"}]
        # Surface sample row keys + value preview for LLM ergonomics
        sample_hint = ""
        for port in ports:
            blob = result.get(port) or {}
            if isinstance(blob, dict):
                sr = blob.get("sample_rows") or []
                cols = blob.get("columns") or []
                if sr and isinstance(sr[0], dict):
                    sample_hint = f" cols={cols[:8]}{'…' if len(cols) > 8 else ''}"
                    break
        positive = ""
        if isinstance(rows, int) and rows >= 1:
            positive = " -- has data; if this satisfies the phase goal, call phase_complete next round"
        return f"got output for {nid}: rows={rows} ports={ports}{sample_hint}{positive}"
    if tool == "add_node":
        nid = result.get("node_id")
        return f"added node id={nid}"
    if tool == "connect":
        return f"edge_id={result.get('edge_id')}"
    if tool == "set_param":
        return "param updated"
    if tool == "remove_node":
        return f"removed node + {len(result.get('removed_edges') or [])} edges"
    if tool == "phase_complete":
        v_says = result.get("verifier_says")
        if v_says is None:
            return "phase_complete signal sent (verifier accepted)"
        return f"phase_complete REJECTED by verifier: {v_says.get('reason')}"
    return str(result)[:120]


def _check_phase_done(
    pipeline: PipelineJSON,
    phase: dict,
    registry: SeedlessBlockRegistry,
) -> dict[str, Any]:
    """Deterministic phase completion verifier per `expected` kind.

    Returns {match: bool, reason: str, ...}.
    """
    expected = phase.get("expected") or "transform"
    nodes = pipeline.nodes
    if not nodes:
        return {"match": False, "reason": "no nodes on canvas"}

    # Find terminal nodes (no outgoing edges).
    # EdgeEndpoint has `.node` (the referenced node id) and `.port`, NOT `.id`.
    outgoing = {e.from_.node for e in pipeline.edges}
    terminal_ids = [n.id for n in nodes if n.id not in outgoing]

    if not terminal_ids:
        return {"match": False, "reason": "no terminal node identified"}

    # Inspect the last-added terminal (most recent build progress)
    target = nodes[-1]
    target_spec = registry.get_spec(target.block_id, target.block_version) or {}
    category = target_spec.get("category", "")
    output_types = [p.get("type") for p in (target_spec.get("output_schema") or [])]

    # Helper: check if a node's preview snapshot has rows >= min_rows
    def _has_rows(node_id: str, min_rows: int = 1) -> bool:
        try:
            # Quick async-less check via toolset preview is too heavy here;
            # rely on auto_preview_result already attached upstream OR caller
            # passes via context. Conservative default: assume yes if node exists.
            return True
        except Exception:
            return False

    if expected == "raw_data":
        ok = category == "source"
        return {"match": ok, "reason": f"terminal category={category}", "got": "source" if ok else category}
    if expected == "transform":
        # Tighter: need dataframe output AND auto-preview must have produced
        # rows >= 1 (avoid auto-completing on empty filter results).
        ok_type = "dataframe" in output_types
        # The caller has just run preview; we can read the result via the
        # outer auto_preview_result, but it's not in this scope. Use a
        # conservative pre-check: dataframe-type counts as ok; phase loop
        # will catch empty-rows downstream when next phase tries to act.
        return {"match": ok_type, "reason": f"terminal dataframe? {ok_type}", "got": output_types}
    if expected == "verdict":
        ok = target.block_id in {"block_step_check", "block_threshold"}
        return {"match": ok, "reason": f"terminal is verdict block? {ok}", "got": target.block_id}
    if expected == "chart":
        ok = category == "output" and any("chart_spec" in str(t) for t in output_types)
        return {"match": ok, "reason": f"terminal chart? {ok}", "got": f"{category}/{output_types}"}
    if expected == "table":
        ok = target.block_id == "block_data_view"
        return {"match": ok, "reason": f"terminal is data_view? {ok}", "got": target.block_id}
    if expected == "scalar":
        ok = any(t in {"bool", "scalar", "number"} for t in output_types)
        return {"match": ok, "reason": f"terminal scalar? {ok}", "got": output_types}
    if expected == "alarm":
        ok = target.block_id in {"block_alert", "block_any_trigger"}
        return {"match": ok, "reason": f"terminal is alarm? {ok}", "got": target.block_id}
    return {"match": False, "reason": f"unknown expected={expected}"}


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
