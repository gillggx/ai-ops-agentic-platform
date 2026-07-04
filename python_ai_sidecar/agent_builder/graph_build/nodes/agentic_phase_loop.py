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
from python_ai_sidecar.feature_flags import (
    is_auto_verifier_enabled,
    is_construct_param_doc_enabled,
    is_execute_knowledge_enabled,
    is_goal_aware_matching_enabled,
    is_next_memo_enabled,
    is_prompt_cache_enabled,
    is_rich_schema_values_enabled,
)
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


# Phase 0 (2026-07-02): budget single-source — the value lives on the
# BuilderAgent (agents/builder.py BUILDER_BUDGETS). History: 32 since
# 2026-06-13 (was 16) — multi-block phases (unnest+filter+step_check) need
# 4 rounds per block × 3 blocks = 12 minimum, with margin for re-inspects.
from python_ai_sidecar.agent_builder.agents.builder import BUILDER_BUDGETS

MAX_REACT_ROUNDS = BUILDER_BUDGETS.react_rounds
MAX_INSPECT_CALLS_PER_ROUND = 5
# v30.24: consecutive reasoning-only (no tool call) responses before we stop
# re-asking and escalate to phase_revise. See the tool_call-is-None branch.
MAX_CONSECUTIVE_NO_ACTION = 3
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
6. 選錯 block (block_id 本身錯) -> `remove_node(node_id)` 再 add_node 對的

== 修錯 node 的決策原則 (v30.24, 2026-06-01) ==
add_node 後 verifier 報 `validation_error` 或 `param missing` 時，正確反應**只有一個**：
  ✓ **`set_param(原 node_id, key, 正確值)` 修現有 node**
不要做以下任何一件事：
  ✗ 再 add_node 一個「空 params 殼」打算稍後 set_param — 會留 orphan，後面常忘了補
  ✗ 連續多 round 探究「是 schema 還是 wrapping 還是 type 問題」 — 直接讀 verifier 給的
     error_message 找確切缺什麼 key / value，一個 set_param 處理完
  ✗ remove_node 再 add_node 同一 block_id 想「重來」— 純浪費 round，preview snapshot 不變

唯一該 remove_node 的情境：你發現整個 block_id 選錯（要換成另一個 block）。
只是 param 不對 = `set_param` 修；不要 remove 後加新的空殼。

== Phase 達成 — 你決定何時 verify (v30.22, 2026-05-19) ==
verifier **不再** 每個 action 後自動跑。你可以自由 add_node / connect /
set_param **多個 block** 建一條 chain（如 OOC 計數要 `filter → step_check`
兩 block）。當你覺得這個 phase 的 chain 建完整了，**主動呼叫
`run_verifier()`** 觸發 verifier 檢查。

verifier 跑時會做 deterministic 結構檢查 (不是 LLM judge):
  (a) validation_error: 鏈上任何 block executor 短路 / params 錯
  (b) orphan: 非 source block 沒接上游
  (c) covers gate: terminal block 的 covers 是否含 phase.expected
      — **預設關閉** (BUILDER_VERIFIER_COVERS_GATE=1 才開)。
      phase.expected 仍是 plan / prompt 內的「目標 hint」, 但不擋你 advance。

verifier ADVANCED → 推進下一 phase (composite block 還可 fast-forward 多 phase)。
verifier REJECTED → 留在當前 phase；prompt 會 surface reject 理由
(covers mismatch / validation_error / orphan + would_pass 候選 list)，
你看完可以 set_param 調 / add_node 加更多 / remove_node 重來。

**round 預算**：每 phase 最多 8 round (chart/alarm 12)。沒在預算內叫
run_verifier 也會自動 fallback 觸發一次 — 但通常會 reject。所以該叫就叫。

phase_complete 為 legacy alias，效果跟 run_verifier 相同。

== 每步附 reason ==
canvas 工具 (add_node / connect / set_param / remove_node) 都有 optional
`reason` 欄：一句話 (≤30字) 說明為什麼做這一步。這是給 user 看的透明化
說明，不影響執行。有明確理由就帶上；沒有就省略。

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

== Block 選擇原則 (v30.18, 2026-05-18) ==
不要直覺挑 block。選 block 前要走過評估流程:

  1. 看 AVAILABLE BLOCKS 該 category 下所有 candidate 的 1-line desc
  2. 對 top 2-3 候選 `inspect_block_doc(block_id)` 拿完整 doc + 限制 + 適用場景
  3. 評估每個候選是否真的滿足 **當前 phase + 該 phase 後的 chart 需求**
     (e.g. EWMA / Box Plot / Probability Plot 是不同 chart sub-type, 需用對
     應的專用 block, 不是任何 chart block 都能替代)
  4. 確認後再 add_node

寧可多 1 round inspect, 也不要選錯 block 後反覆 remove + re-add。
"composite block 一個解多 phase" 這種 shortcut 只在 user 明確要該 composite
產出的東西時才適用 (e.g. 標準 SPC 管制圖 → spc_panel; EWMA chart →
block_ewma_cusum，不是 spc_panel)。

== Catalog 分兩層 (v50, 2026-06-02) ==
AVAILABLE BLOCKS 列表分兩段：

**TIER 1 — essential blocks**：完整 description + param_schema 已內聯在
prompt。你可以直接 `add_node(block_id, params)`，不必先 inspect_block_doc。
這 10 個 block 覆蓋 80% pipeline 場景。

**TIER 2 — other blocks**：只列名稱 + 一句描述。如果要用 Tier 2 block，
**強制流程**：
  1. 看到 Tier 2 block 名稱覺得合適 (e.g. user 要 normality → block_probability_plot)
  2. **先 `inspect_block_doc(block_id)`** 拿完整 doc + param_schema
  3. **再 `add_node`** 帶正確 params

直接 `add_node` 一個 Tier 2 block 而沒 inspect 過，params 一定會猜錯，
verifier 直接 reject — 浪費 round。不要省這步。
"""


def _load_glossary_safe() -> str:
    """v30.18: load SPC/APC domain glossary into agent's system prompt.
    Same content judge sees, so agent and judge share the canonical pipeline
    pattern (raw → unnest → filter → chart, nested spc_charts structure, etc).
    Returns empty string on import failure (defensive)."""
    try:
        from python_ai_sidecar.agent_builder.graph_build.prompts import (
            load_spc_apc_glossary,
        )
        return "\n\n" + load_spc_apc_glossary()
    except Exception:
        return ""


_SYSTEM = _SYSTEM + _load_glossary_safe()


def _stamp_last_message_cache(messages: list[dict]) -> list[dict]:
    """Return a shallow copy of `messages` with cache_control on the last
    content block. Anthropic caches the prefix up to and including that
    breakpoint, so each subsequent round only pays for the appended delta.

    Handles both string-content messages (round 1 user obs) and
    list-content messages (round 2+ tool_result lists)."""
    if not messages:
        return messages
    out = [dict(m) for m in messages]
    last = out[-1]
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{
            "type": "text", "text": content,
            "cache_control": {"type": "ephemeral"},
        }]
    elif isinstance(content, list) and content:
        new_content = [dict(c) for c in content]
        # Don't mutate tool_use/tool_result shape — just add cache_control
        # on the LAST part. Anthropic accepts cache_control on any block.
        new_content[-1] = {**new_content[-1],
                           "cache_control": {"type": "ephemeral"}}
        last["content"] = new_content
    return out


NO_ACTION_NUDGE = (
    "你上一輪沒有輸出任何 tool call。請直接以一個 tool call 執行你的結論 — "
    "不要只在思考中決定。"
)


def _handle_no_action(
    state: BuildGraphState,
    *,
    pid: str,
    round_n: int,
    phase_messages: list[dict],
    assistant_content: list[dict] | None,
) -> dict[str, Any]:
    """v30.24: consecutive empty-response guard (pure, unit-testable).

    Some providers return reasoning-only completions (finish_reason=stop,
    empty content, no tool call). Re-calling with byte-identical context
    repeats the failure deterministically — so (a) append a nudge so the
    next call's context differs, (b) after MAX_CONSECUTIVE_NO_ACTION
    consecutive empties escalate to phase_revise instead of blind-burning
    the full round budget while the UI looks frozen.
    """
    # v30.23: strip ANY tool_use blocks from assistant_content before
    # appending — we have no tool_result to pair them with (no dispatch
    # happened). Without this Anthropic API rejects next call with
    # "tool_use without tool_result".
    if assistant_content:
        assistant_content = [
            b for b in assistant_content if b.get("type") != "tool_use"
        ]

    no_action_map = dict(state.get("v30_phase_no_action") or {})
    no_action_n = no_action_map.get(pid, 0) + 1
    no_action_map[pid] = no_action_n

    if no_action_n >= MAX_CONSECUTIVE_NO_ACTION:
        logger.warning(
            "agentic_phase_loop: phase %s — %d consecutive empty LLM "
            "responses (round %d) — escalate to revise",
            pid, no_action_n, round_n + 1,
        )
        # Reset so the post-revise retry gets the full consecutive-empty
        # budget again — without this the retried phase re-escalates on its
        # FIRST empty response (observed in smoke5-b1guard: escalated at 3,
        # then again immediately after revise).
        no_action_map[pid] = 0
        return {
            "status": "phase_revise_pending",
            "v30_phase_no_action": no_action_map,
            "sse_events": [_event("phase_revise_started", {
                "phase_id": pid, "reason": "empty_llm_responses",
                "consecutive_no_action": no_action_n,
            })],
        }

    # Nudge: a plain user message breaks the identical-context repeat.
    # Keep the assistant turn in between (real content when the model
    # produced text; a placeholder otherwise) so roles stay alternating.
    phase_messages.append({
        "role": "assistant",
        "content": assistant_content
        or [{"type": "text", "text": "(沒有輸出任何 tool call)"}],
    })
    phase_messages.append({"role": "user", "content": NO_ACTION_NUDGE})
    new_msgs = dict(state.get("v30_phase_messages") or {})
    new_msgs[pid] = phase_messages
    return {
        "v30_phase_round": round_n + 1,
        "v30_phase_messages": new_msgs,
        "v30_phase_no_action": no_action_map,
        "sse_events": [_event("phase_round", {
            "phase_id": pid, "round": round_n + 1, "max": MAX_REACT_ROUNDS,
            "no_action": True, "consecutive_no_action": no_action_n,
        })],
    }


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

    # v30.19 (Q2 follow-up A): per-phase round budget. alarm phases tend
    # to involve multi-step alert+connect sequences (often after the agent
    # confuses verdict vs alarm blocks); give them more headroom. chart
    # phases sometimes need filter+chart_block iteration too.
    phase_round_cap = MAX_REACT_ROUNDS
    if (phase.get("expected") or "") in {"alarm", "chart"}:
        # 2026-06-13: was 12 (< MAX_REACT_ROUNDS) — a stale special-case from
        # when the default was 8. alarm/chart phases often chain filter+chart,
        # so they need AT LEAST the default, not less. Keep them at the default.
        phase_round_cap = MAX_REACT_ROUNDS
    # Round cap check
    if round_n >= phase_round_cap:
        logger.warning(
            "agentic_phase_loop: phase %s exhausted %d rounds (cap=%d, expected=%s) — escalate to revise",
            pid, round_n, phase_round_cap, phase.get("expected"),
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
    # v30.19 (2026-05-19) — per-node lifecycle sub-phase. Tool subset per
    # sub-state forces the lifecycle to happen in graph (filter), not in
    # prompt suggestion. Default sub_phase=None at phase entry → seeded
    # to "pick".
    cur_subphase = state.get("v30_subphase") or "pick"
    tool_specs = _filter_tool_specs_for_subphase(_build_tool_specs(), cur_subphase)
    phase_messages = list(
        (state.get("v30_phase_messages") or {}).get(pid, [])
    )
    if not phase_messages:
        # First round of this phase — seed with full observation
        sub_hint = _build_subphase_hint(cur_subphase, state)
        seeded = sub_hint + "\n\n" + full_user_msg if sub_hint else full_user_msg
        # V58: execute-layer knowledge — block-choice rules (agent_knowledge
        # applies_to ∈ {execute,both}) RAG'd by THIS phase's goal, injected once
        # at phase entry (the pick sub-phase). goal_plan is block-agnostic and
        # can't carry "全廠 → list_objects + foreach"; this puts it in front of
        # the agent exactly when it picks the source block. Top-2 RAG only, no
        # always-on dump — keep the pick prompt lean (feedback_verbose_catalog).
        if is_execute_knowledge_enabled():
            try:
                from python_ai_sidecar.agent_builder.graph_build.nodes._knowledge_inject import (
                    build_knowledge_hint,
                )
                # rag_limit=3: the recall harness (tools/knowledge_recall)
                # showed the spc-ooc fan-out entry (id 36) lands at rank 3 for
                # its phase goal, so top-2 would miss it. 3 short bodies once
                # per phase is still lean.
                exec_know = await build_knowledge_hint(
                    phase.get("goal") or state.get("instruction", ""),
                    user_id=state.get("user_id") or 1, source="phase_exec",
                    layer="execute", include_always_on=False, rag_limit=3,
                    agent="builder", phase_id=phase.get("id"),
                    round=state.get("v30_phase_round"),
                )
                if exec_know:
                    seeded = seeded + exec_know
            except Exception as ex:  # noqa: BLE001
                logger.info("phase_loop: execute knowledge inject skipped (%s)", ex)
        phase_messages.append({"role": "user", "content": seeded})

    # 2026-05-22: Prompt cache (Anthropic ephemeral).
    # cache_control on the LAST tool caches system + tools across all rounds
    # of this phase (and same phase across subsequent builds within 5 min).
    # cache_control on the LAST message caches the full prior conversation
    # so each round only pays for the newly-appended user/tool_result delta.
    # Gated behind ENABLE_PROMPT_CACHE feature flag (2026-06-11) so we can A/B.
    cache_on = is_prompt_cache_enabled()
    if cache_on:
        system_blocks = [{"type": "text", "text": _SYSTEM,
                          "cache_control": {"type": "ephemeral"}}]
        cached_tools = [dict(t) for t in tool_specs]
        if cached_tools:
            cached_tools[-1] = {**cached_tools[-1],
                                "cache_control": {"type": "ephemeral"}}
        cached_messages = _stamp_last_message_cache(phase_messages)
    else:
        system_blocks = _SYSTEM
        cached_tools = tool_specs
        cached_messages = phase_messages
    try:
        resp = await client.create(
            system=system_blocks,
            messages=cached_messages,
            tools=cached_tools,
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
                                    parts.append(f"[tool_result: {str(p.get('content',''))[:6000]}]")
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
    # _decision_entry is captured here and gets its `tool_result` attached
    # AFTER dispatch (the action hasn't run yet at this point).
    _decision_entry: dict[str, Any] | None = None
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
            _decision_entry = tracer.record_decision(
                node="agentic_phase_loop",
                phase_id=pid, round=round_n + 1,
                sub_phase=cur_subphase,
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
        patch = _handle_no_action(
            state, pid=pid, round_n=round_n,
            phase_messages=phase_messages,
            assistant_content=assistant_content,
        )
        if tracer is not None and patch.get("status") == "phase_revise_pending":
            _ev_data = (patch.get("sse_events") or [{}])[0].get("data") or {}
            tracer.record_step(
                "agentic_phase_loop", status="empty_response_escalated",
                phase_id=pid, round=round_n + 1,
                consecutive_no_action=_ev_data.get("consecutive_no_action"),
            )
        return patch

    tool_name = tool_call["name"]
    tool_args = tool_call.get("args") or {}
    tool_use_id = tool_call.get("id")

    # ── Stuck detector ────────────────────────────────────────────────
    recent_actions = (state.get("v30_phase_recent_actions") or {}).get(pid, [])
    args_hash = _hash_action(tool_name, tool_args)

    # v30.23 — doc-reread signal. Agent re-inspecting the same block doc
    # within one phase suggests the doc didn't deliver what the agent
    # needed first time. Log a structured WARN so we can surface "blocks
    # most often re-inspected" as a doc-quality backlog. Not an error —
    # agent is free to re-read; we just want the signal.
    if tool_name == "inspect_block_doc":
        target_block = (tool_args or {}).get("block_id")
        # args_hash is deterministic per (tool, args) — same block_id call
        # → same hash. Count exact-match priors for this block within phase.
        prior_reads = sum(
            1 for a in recent_actions
            if a.get("tool") == "inspect_block_doc"
            and a.get("args_hash") == args_hash
        )
        if prior_reads >= 1:
            logger.warning(
                "doc_reread_signal: phase=%s block=%s read_count=%d "
                "(agent re-inspecting — doc may be unclear)",
                pid, target_block, prior_reads + 1,
            )
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
    # Item 1 (ENABLE_NEXT_MEMO): `next` is a planning memo carried in the tool
    # args for the agent's benefit — NOT an executor argument. Strip it before
    # dispatch so it never reaches BuilderToolset.add_node(**args) (which would
    # TypeError and silently fail the whole mutation). tool_args stays intact for
    # the memo capture + trace below.
    # B3 (2026-07-04): `reason` is the Agent Console's 三段式「理由」— same
    # treatment as `next`: shipped in phase_action.tool_args_raw for the UI,
    # never passed to the executor.
    exec_args = tool_args
    if isinstance(tool_args, dict) and ("next" in tool_args or "reason" in tool_args):
        exec_args = {k: v for k, v in tool_args.items() if k not in ("next", "reason")}
    # v30.19: signal tools (commit_pick / abort_*/run_verifier) don't go
    # through toolset — they only drive sub-phase transitions.
    if tool_name in _SIGNAL_TOOLS:
        action_result = _handle_signal_tool(tool_name, exec_args)
    else:
        try:
            method = getattr(toolset, tool_name, None)
            if method is None or not callable(method):
                raise ToolError(code="UNKNOWN_TOOL", message=f"No tool {tool_name}")
            action_result = await method(**exec_args)
        except ToolError as e:
            logger.info("agentic_phase_loop: tool %s failed: %s", tool_name, e.message)
            action_result = {"error": e.message, "code": e.code, "hint": e.hint}
        except Exception as e:  # noqa: BLE001
            logger.warning("agentic_phase_loop: tool %s threw: %s", tool_name, e)
            action_result = {"error": f"{type(e).__name__}: {e}"}

    # Trace gap #3 (2026-06-14): attach the action's result to THIS round's
    # decision record so one trace shows what the agent saw (inspect cols/sample,
    # errors) — previously only reconstructable from the next round's user_msg.
    if _decision_entry is not None and isinstance(action_result, dict):
        _decision_entry["tool_result"] = {
            k: str(v)[:800] for k, v in action_result.items()
        }

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
                # 2026-05-23: toolset.preview() returns `errors` (plural,
                # list) when PipelineValidator rejects subgraph, and `error`
                # (singular, string) when executor crashes at runtime. The
                # snapshot here previously read only `error`, so validator
                # rejections were silently dropped → phase_verifier reported
                # "(no error message captured)" and the agent looped trying
                # to fix something it couldn't see. Coalesce both shapes
                # into a single error string for downstream consumers.
                _err = _coalesce_preview_error(pv)
                snapshot_dict = {
                    "logical_id": target_nid,
                    "real_id": target_nid,
                    "block_id": blk_id,
                    "rows": pv.get("rows"),
                    "cols": cols[:20],
                    "sample": sample,
                    "runtime_schema_md": runtime_schema_md,
                    "status": pv.get("status"),
                    "error": _err,
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
    #
    # v30.23 (2026-05-20): LLM sometimes emits MULTIPLE tool_use blocks in
    # one response (multi-call). We dispatch only the first (tool_call from
    # _extract_tool_call). If we append the full assistant_content with N
    # tool_uses but only emit 1 tool_result, Anthropic API rejects next
    # call with "messages.K: tool_use ids were found without tool_result
    # blocks immediately after". Drop the extra tool_use blocks here so
    # msg[i] has exactly 1 tool_use matching msg[i+1]'s 1 tool_result.
    if assistant_content and tool_use_id:
        filtered_content = []
        kept_tool_use = False
        for blk in assistant_content:
            if blk.get("type") == "tool_use":
                if not kept_tool_use and blk.get("id") == tool_use_id:
                    filtered_content.append(blk)
                    kept_tool_use = True
                # drop extras
            else:
                filtered_content.append(blk)
        assistant_content = filtered_content
    if assistant_content:
        phase_messages.append({"role": "assistant", "content": assistant_content})
    if tool_use_id:
        result_digest_text = _make_result_digest(tool_name, action_result)
        # v30.17l hotfix: pass state so canvas_diff_md can include
        # VERIFIER FEEDBACK on follow-up rounds (was only in initial obs_md).
        canvas_diff_text = _build_canvas_diff_md(transient.pipeline_json, phase, state)
        _content = [
            {"type": "tool_result", "tool_use_id": tool_use_id,
             "content": result_digest_text},
            {"type": "text", "text": canvas_diff_text},
        ]
        # 2026-06-17 (rich_schema_values, #2): fold the just-added node's runtime
        # schema (with the true distinct values) into the tool_result so the
        # SAME-phase next round sees what it just produced — without spending an
        # inspect_node_output round to re-learn it.
        if is_rich_schema_values_enabled() and snapshot_dict:
            _new_schema_md = snapshot_dict.get("runtime_schema_md") or ""
            if _new_schema_md:
                _content.append({
                    "type": "text",
                    "text": ("== JUST-PRODUCED OUTPUT (no need to inspect) ==\n"
                             + _new_schema_md),
                })
        phase_messages.append({"role": "user", "content": _content})
    # Cap message stack to avoid runaway token use (~16 round-trips).
    if len(phase_messages) > 32:
        phase_messages = phase_messages[-32:]
    new_msgs = dict(state.get("v30_phase_messages") or {})
    new_msgs[pid] = phase_messages

    # v30.19: compute sub-phase transition (atomic add_node shortcut
    # routes pick/construct/tune → tune in one round when `upstream` set).
    next_sub = _next_subphase(cur_subphase, tool_name, tool_args)
    pending_block_update = None
    pending_node_id_update = None
    if tool_name == "commit_pick":
        pending_block_update = (tool_args or {}).get("block_id")
    elif tool_name == "add_node" and "error" not in action_result:
        pending_node_id_update = action_result.get("node_id") or last_mutated_logical_id
        # ENABLE_AUTO_SIGNAL: if add_node arrived from pick/tune sub-phase
        # without a prior commit_pick, capture block_name as the implicit
        # pick so v30_pending_block stays in sync for downstream consumers
        # (subphase hint, verifier outcome tracking).
        if cur_subphase in ("pick", "tune") and not state.get("v30_pending_block"):
            implicit_block = (tool_args or {}).get("block_name")
            if implicit_block:
                pending_block_update = implicit_block

    # v30.22 (2026-05-19) — agent-driven verify trigger.
    # Verifier runs only when:
    #   (a) agent explicitly emitted run_verifier / phase_complete (legacy)
    #   (b) round budget exhausted — fallback so build doesn't silently spin
    #   (c) ENABLE_AUTO_VERIFIER (2026-06-12) — phase-terminal block landed
    #       AND agent looks decisive (no recent inspect_*)
    # Otherwise loop back so agent can keep adding nodes / connecting /
    # tuning. Lets agent build multi-block chains (e.g. filter→step_check
    # for "count OOC then compare ≥2") without verifier rejecting after
    # the first add_node.
    explicit_verify = tool_name in {"run_verifier", "phase_complete"}
    auto_verify = _should_auto_verify(
        state, phase, tool_name, action_result,
        recent_actions_history=recent_actions,
        transient_pipeline=transient.pipeline_json,
        registry=registry,
    )
    if auto_verify and not explicit_verify:
        logger.info(
            "agentic_phase_loop: auto-verifier triggered for phase=%s after %s "
            "(terminal block matches expected=%s, agent looks decisive)",
            pid, tool_name, phase.get("expected"),
        )
    verify_now = explicit_verify or auto_verify

    state_update: dict[str, Any] = {
        "v30_phase_round": round_n + 1,
        "v30_phase_recent_actions": new_recent,
        "v30_phase_messages": new_msgs,
        "final_pipeline": new_pipeline_dict,
        "v30_verify_now": verify_now,
    }
    # v30.24: a real tool call resets the consecutive-empty counter.
    if (state.get("v30_phase_no_action") or {}).get(pid):
        _na = dict(state.get("v30_phase_no_action") or {})
        _na[pid] = 0
        state_update["v30_phase_no_action"] = _na
    # Item 1 (ENABLE_NEXT_MEMO): carry the agent's planned next step forward so
    # the next round's prompt can surface it (multi-block intent survives).
    if is_next_memo_enabled():
        if tool_name in {"add_node", "set_param", "connect", "remove_node"}:
            _memo = (tool_args or {}).get("next")
            # Only carry the memo forward if the mutation SUCCEEDED — a failed
            # add_node didn't create the node the memo likely references, so a
            # stale memo would point the agent at a phantom node next round.
            _ok = "error" not in (action_result or {})
            state_update["v30_next_memo"] = str(_memo)[:300] if (_memo and _ok) else None
        elif tool_name in {"phase_complete", "run_verifier", "abort_phase"}:
            state_update["v30_next_memo"] = None  # done/abort signal clears the plan
    if next_sub is not None and next_sub != cur_subphase:
        state_update["v30_subphase"] = next_sub
        state_update["v30_subphase_round"] = 0
        logger.info("agentic_phase_loop: sub-phase %s → %s (tool=%s)",
                    cur_subphase, next_sub, tool_name)
    else:
        state_update["v30_subphase_round"] = (state.get("v30_subphase_round") or 0) + 1
    if pending_block_update:
        state_update["v30_pending_block"] = pending_block_update
    if pending_node_id_update:
        state_update["v30_pending_node_id"] = pending_node_id_update

    # v30.1 (2026-05-16): hand off mutation snapshot to phase_verifier_node.
    # Verifier reads these to decide phase advancement + extract outcome
    # values for the fast-forward report. None for inspect-only rounds.
    if last_mutated_logical_id and snapshot_dict:
        new_exec_trace = dict(state.get("exec_trace") or {})
        new_exec_trace[last_mutated_logical_id] = snapshot_dict
        state_update["exec_trace"] = new_exec_trace
        state_update["v30_last_mutated_logical_id"] = last_mutated_logical_id
        state_update["v30_last_preview"] = auto_preview_blob
    elif verify_now:
        # v30.22: agent emitted run_verifier / phase_complete (signal tool,
        # not a mutation). Point verifier at the canvas terminal (latest
        # added node with no outgoing edges) so verifier knows what to
        # check. Without this verifier would early-return because last_lid
        # is None — agent's "I'm done" signal would be silently ignored.
        terminal_lid, terminal_preview = _find_canvas_terminal(
            transient.pipeline_json, state.get("exec_trace") or {},
            expected=(phase.get("expected") or ""),
            registry=registry,
        )
        if terminal_lid:
            # hardening #3 (2026-06-25): re-preview the terminal NOW so the
            # verifier reads its CURRENT status + error. run_verifier is a
            # signal tool (no auto-preview this round), so exec_trace[terminal]
            # may be stale or absent — a failing terminal then surfaces
            # "(no error message captured)" and the agent loops blind.
            try:
                fresh = await _fresh_terminal_snapshot(
                    toolset, transient.pipeline_json, terminal_lid, round_n,
                )
                if fresh is not None:
                    new_exec_trace = dict(state.get("exec_trace") or {})
                    new_exec_trace[terminal_lid] = fresh
                    state_update["exec_trace"] = new_exec_trace
            except Exception as ex:  # noqa: BLE001
                logger.info("run_verifier fresh preview failed (non-fatal): %s", ex)
            state_update["v30_last_mutated_logical_id"] = terminal_lid
            state_update["v30_last_preview"] = terminal_preview
            logger.info(
                "agentic_phase_loop: %s pointing verifier at canvas terminal "
                "%s (no recent mutation)", tool_name, terminal_lid,
            )
        else:
            # Empty canvas — verifier will reject phase as not built
            state_update["v30_last_mutated_logical_id"] = None
            state_update["v30_last_preview"] = None
    else:
        # Explicit clear so verifier no-ops on inspect-only / errored rounds.
        state_update["v30_last_mutated_logical_id"] = None
        state_update["v30_last_preview"] = None

    # Pipeline snapshot for frontend canvas re-render after canvas-mutating
    # actions. Cheap (just dump model). Skip for inspect_* / phase_complete.
    pipeline_snapshot = None
    if tool_name in mutating:
        pipeline_snapshot = new_pipeline_dict

    # v30.23 (2026-05-20) — coerce tool_args.params if the agent emitted
    # stringified JSON. Server-side tools._coerce_params_dict already
    # parsed it before storing on the canvas, but tool_args (local var)
    # still holds the raw string. Without re-coercion here, the SSE
    # phase_action.tool_args_raw ships the string to frontend Lite
    # Canvas, which iterates it as a dict → renders char-indexed garbage
    # like {0:'{', 1:'"', 2:'c'}. Try Run then errors on the broken
    # params blob.
    if tool_name == "add_node" and isinstance(tool_args.get("params"), str):
        try:
            tool_args = dict(tool_args)
            tool_args["params"] = json.loads(tool_args["params"])
        except (json.JSONDecodeError, TypeError):
            pass  # leave as-is; frontend will surface whatever's there

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
            # v30.23: check VALUE not key presence. inspect_node_output
            # always includes "error": None even on success; old check
            # flagged every successful inspect as action_ok=False.
            action_ok=not bool(action_result.get("error") if isinstance(action_result, dict) else None),
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
                                f"[tool_result: {str(p.get('content',''))[:6000]}]"
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


_BLOCK_HEADLINE_CACHE: dict[str, str] | None = None
_BLOCK_HEADLINE_CACHE_TS: float = 0.0
_BLOCK_HEADLINE_TTL_SEC: float = 300.0


async def _load_block_headlines_from_db() -> dict[str, str]:
    """V49 (2026-05-19): bulk fetch frontmatter `description` from block_docs.
    Used as the catalog brief 1-line summary (preferred over baked seed)."""
    import time as _t
    global _BLOCK_HEADLINE_CACHE, _BLOCK_HEADLINE_CACHE_TS
    now = _t.time()
    if _BLOCK_HEADLINE_CACHE is not None and (now - _BLOCK_HEADLINE_CACHE_TS) < _BLOCK_HEADLINE_TTL_SEC:
        return _BLOCK_HEADLINE_CACHE
    from python_ai_sidecar.clients.java_client import JavaAPIClient
    from python_ai_sidecar.config import CONFIG
    import re as _re
    result: dict[str, str] = {}
    try:
        java = JavaAPIClient(
            base_url=CONFIG.java_api_url,
            token=CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        docs = await java.list_block_docs()
        for d in (docs or []):
            block_id = d.get("blockId") or d.get("block_id")
            md = d.get("markdown") or ""
            if not block_id or not md:
                continue
            # Parse frontmatter description
            m = _re.match(r"^---\s*\n(.+?)\n---\s*\n", md, _re.DOTALL)
            if not m:
                continue
            for line in m.group(1).splitlines():
                if line.startswith("description:"):
                    desc = line.split(":", 1)[1].strip()
                    if desc:
                        result[block_id] = desc[:200]
                    break
    except Exception:  # noqa: BLE001 — fall back to baked
        pass
    _BLOCK_HEADLINE_CACHE = result
    _BLOCK_HEADLINE_CACHE_TS = now
    return result


def _build_catalog_brief() -> str:
    """Render the block catalog for the agent system prompt.

    Two-tier layout:
      - Tier 1 (essential=True in seed.py): full description (truncated to
        ~1.5KB / block) + param schema. Agent picks them without an extra
        inspect_block_doc round.
      - Tier 2 (everything else): single index line `name -- one-liner`.
        Agent MUST call `inspect_block_doc(block_id)` before `add_node` to
        get full params — index line is not enough.

    Process-cached (catalog content is constant per deploy).

    v49 (2026-05-19): prefer DB block_docs.frontmatter.description over
    baked seed.py `== What ==` parsing for one-liners. Falls back gracefully.
    v50 (2026-06-02): tiered catalog. See docs/llm-provider-audit-2026-06-01.md
    """
    global _CATALOG_BRIEF_CACHE
    if _CATALOG_BRIEF_CACHE is not None:
        return _CATALOG_BRIEF_CACHE

    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    import asyncio
    import re
    registry = SeedlessBlockRegistry()
    registry.load()

    # Best-effort DB fetch — non-blocking via run_until_complete on a new
    # loop when none active; tolerate failure silently.
    headlines_db: dict[str, str] = {}
    try:
        loop = asyncio.new_event_loop()
        try:
            headlines_db = loop.run_until_complete(_load_block_headlines_from_db())
        finally:
            loop.close()
    except Exception:  # noqa: BLE001
        headlines_db = {}

    # Tier1 = essential; Tier2 = everything else. Group both by category
    # for readability so LLM sees `[transform]` once with essentials first.
    tier1_by_cat: dict[str, list[tuple[str, dict]]] = {}
    tier2_by_cat: dict[str, list[str]] = {}
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        cat = spec.get("category") or "transform"
        essential = bool(spec.get("essential"))
        if essential:
            tier1_by_cat.setdefault(cat, []).append((name, spec))
            continue
        # Tier 2 — single index line
        what_line = headlines_db.get(name) or ""
        if not what_line:
            desc = (spec.get("description") or "").strip()
            m = re.search(r"== What ==\s*\n+(.+?)(?:\n\n|\n==)", desc, re.DOTALL)
            if m:
                what_line = m.group(1).strip().split("\n")[0][:90]
            else:
                what_line = desc.split("\n", 1)[0][:90]
        tier2_by_cat.setdefault(cat, []).append(f"  {name}  -- {what_line}")

    lines: list[str] = []
    lines.append("=== TIER 1 — essential blocks (full spec inline) ===")
    lines.append("These cover the common 80% of pipelines. You may add_node directly.")
    lines.append("")
    for cat in sorted(tier1_by_cat.keys()):
        lines.append(f"[{cat}]")
        for name, spec in sorted(tier1_by_cat[cat], key=lambda x: x[0]):
            lines.append(f"--- {name} ---")
            desc = (spec.get("description") or "").strip()
            # Truncate description to ~1500 chars to bound prompt size.
            # Keeps the first 1500 chars which always include "== What ==",
            # usually "== When to use ==", and parts of "== Params ==".
            if len(desc) > 1500:
                desc = desc[:1500] + "\n... [doc truncated; call inspect_block_doc for full]"
            lines.append(desc)
            param_lines = _fmt_param_schema_lines(spec.get("param_schema") or {})
            lines.append("[param_schema]")
            lines.append(param_lines)
            lines.append("")
        lines.append("")

    lines.append("=== TIER 2 — other blocks (index only) ===")
    lines.append(
        "Name + one-liner only. **You MUST call `inspect_block_doc(block_id)` "
        "before `add_node`** — the one-liner is not enough to pick correct "
        "params, and add_node with guessed params will be rejected by the "
        "verifier. If a Tier 2 block's one-liner sounds like what the phase "
        "needs (e.g. user asked for normality plot → block_probability_plot), "
        "inspect it before adding."
    )
    lines.append("")
    for cat in sorted(tier2_by_cat.keys()):
        lines.append(f"[{cat}]")
        for entry in sorted(tier2_by_cat[cat]):
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
        internal_covers = _resolve_covers(spec, kind="internal")
        # Eligibility uses covers_internal so composite blocks (spc_panel:
        # internal=[raw_data, transform, verdict, chart]) surface in raw_data
        # / transform phases too. Verifier's FF walk on covers_internal will
        # accept them; rows-gate fires only at the chain's terminal (where
        # ph_expected ∈ covers_output).
        if cur_expected not in internal_covers:
            continue

        internal_extras = sorted(set(internal_covers) - set(output_covers))
        is_composite = bool(internal_extras)

        # Contiguous chain — what verifier will actually fast-forward (uses
        # covers_internal to match the verifier's chain-membership rule).
        ff_ids: list[str] = []
        for nxt in remaining_phases:
            nxt_exp = (nxt.get("expected") or "").strip()
            if nxt_exp and nxt_exp in internal_covers:
                ff_ids.append(nxt.get("id"))
            else:
                break  # contiguous-only chain (matches verifier semantics)

        # Non-contiguous coverage — what this block COULD eventually satisfy
        # in later phases, even if a non-covered phase intervenes.
        future_covered = [
            nxt.get("id") for nxt in remaining_phases
            if (nxt.get("expected") or "").strip() in internal_covers
        ]

        # Composite block must have at least one terminal in the chain
        # where covers_output matches — else there's no port to rows-gate.
        chain_kinds = {cur_expected} | {
            (remaining_phases[i].get("expected") or "").strip()
            for i in range(len(ff_ids))
        }
        has_output_terminal = bool(chain_kinds & set(output_covers))
        if not has_output_terminal:
            continue

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
        "Server 比對 phase.expected 與 block.produces.covers_internal 算出（事實，非建議）。",
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


# ─────────────────────────────────────────────────────────────────────
# Round 3 (2026-06-12) — context-aware per-sub-phase prompt assembly.
# See docs/agent-subphase-prompt-design.html. Gated by
# ENABLE_RICH_CANVAS_SNAPSHOT. Data source: exec_trace[node_id] (already
# populated after every mutating action with cols + sample).
# ─────────────────────────────────────────────────────────────────────

_MAX_COLS_INLINE = 30        # cols listed before "(+N more)"
_SAMPLE_CAP_CONSTRUCT = 600  # sample chars in construct context
_SAMPLE_CAP_PICK = 200       # terminal sample chars in pick flow tree


def _flatten_sample_one_level(sample: Any, max_chars: int) -> str:
    """Render a sample row dict as a compact one-level-flat string.

    Nested dict / list values are collapsed to ``{...}`` / ``[...]`` so the
    output stays readable and bounded. Returns ``""`` for non-dict input.
    Total length is capped at ``max_chars`` (truncated with a trailing ``…``).
    """
    if not isinstance(sample, dict) or not sample:
        return ""
    parts: list[str] = []
    for k, v in sample.items():
        if isinstance(v, dict):
            rendered = "{...}"
        elif isinstance(v, (list, tuple)):
            rendered = "[...]"
        elif isinstance(v, str):
            rendered = repr(v if len(v) <= 30 else v[:27] + "…")
        else:
            rendered = repr(v)
        parts.append(f"{k}: {rendered}")
    out = "{" + ", ".join(parts) + "}"
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def _node_cols(exec_trace: dict, node_id: str) -> list[str]:
    snap = exec_trace.get(node_id)
    if isinstance(snap, dict):
        cols = snap.get("cols")
        if isinstance(cols, list):
            return [str(c) for c in cols]
    return []


def _fmt_cols_inline(cols: list[str]) -> str:
    if not cols:
        return ""
    shown = cols[:_MAX_COLS_INLINE]
    suffix = f" …(+{len(cols) - _MAX_COLS_INLINE} more)" if len(cols) > _MAX_COLS_INLINE else ""
    return "[" + ", ".join(shown) + "]" + suffix


def _build_node_data_md(
    exec_trace: dict, node_id: str, block_id: str, *,
    sample_cap: int, label: str = "",
) -> list[str]:
    """Return prompt lines describing a node's runtime output (cols + sample).

    Falls back to a "(not yet previewed)" marker when exec_trace has no
    snapshot for the node — never raises.
    """
    snap = exec_trace.get(node_id)
    head = f"{label}{node_id} [{block_id}]" if label else f"{node_id} [{block_id}]"
    if not isinstance(snap, dict):
        return [f"  {head}  (not yet previewed — inspect_node_output to see cols)"]
    lines = [f"  {head}"]
    cols = _node_cols(exec_trace, node_id)
    if cols:
        lines.append(f"     output cols: {_fmt_cols_inline(cols)}")
    sample = snap.get("sample")
    flat = _flatten_sample_one_level(sample, sample_cap)
    if flat:
        lines.append(f"     sample: {flat}")
    return lines


def _build_flow_tree_md(pipeline: PipelineJSON, exec_trace: dict) -> str:
    """Render the pipeline as a source→…→terminal tree for the pick sub-phase.

    Marks canvas terminal(s) (nodes with no outgoing edge) and surfaces the
    terminal node's output cols inline so the agent can pick the next block
    against real available columns instead of guessing.
    """
    if not pipeline.nodes:
        return "== FLOW SO FAR ==\n  (empty canvas — pick the first source block)"
    outgoing = {e.from_.node for e in pipeline.edges}
    incoming = {e.to.node for e in pipeline.edges}
    # Build adjacency: node -> [downstream nodes]
    children: dict[str, list[str]] = {}
    for e in pipeline.edges:
        children.setdefault(e.from_.node, []).append(e.to.node)
    by_id = {n.id: n for n in pipeline.nodes}
    roots = [n.id for n in pipeline.nodes if n.id not in incoming]
    if not roots:  # cyclic / all-connected fallback — list flat
        roots = [pipeline.nodes[0].id]

    lines = ["== FLOW SO FAR =="]
    seen: set[str] = set()

    def _emit(nid: str, depth: int) -> None:
        if nid in seen:
            return
        seen.add(nid)
        node = by_id.get(nid)
        if node is None:
            return
        is_terminal = nid not in outgoing
        is_source = nid not in incoming
        prefix = "  " + ("    " * depth)
        connector = "[source] " if is_source else "└─> "
        params_short = ", ".join(
            f"{k}={v!r}"[:28] for k, v in (node.params or {}).items()
        )[:90]
        marker = "   <- canvas terminal" if is_terminal else ""
        lines.append(f"{prefix}{connector}{nid} {node.block_id}({params_short}){marker}")
        if is_terminal:
            cols = _node_cols(exec_trace, nid)
            if cols:
                lines.append(f"{prefix}     terminal cols: {_fmt_cols_inline(cols)}")
        for child in children.get(nid, []):
            _emit(child, depth + 1)

    for r in roots:
        _emit(r, 0)
    # Catch any nodes not reached (disconnected) so they're not hidden.
    for n in pipeline.nodes:
        if n.id not in seen:
            _emit(n.id, 0)
    return "\n".join(lines)


def _find_committed_block(state: dict | None) -> str | None:
    """The block_id the agent just committed to (construct sub-phase target)."""
    if not state:
        return None
    return state.get("v30_pending_block")


def _terminal_node_ids(pipeline: PipelineJSON) -> list[str]:
    outgoing = {e.from_.node for e in pipeline.edges}
    return [n.id for n in pipeline.nodes if n.id not in outgoing]


# Item 3 (2026-06-13): cached seed.py registry for param-doc lookup. seed.py is
# parsed in-process (no DB), so one load is cheap; cache avoids re-parsing every
# prompt build.
_PARAM_DOC_REGISTRY: SeedlessBlockRegistry | None = None


def _get_block_spec(block_id: str) -> dict | None:
    global _PARAM_DOC_REGISTRY
    if _PARAM_DOC_REGISTRY is None:
        reg = SeedlessBlockRegistry()
        reg.load()
        _PARAM_DOC_REGISTRY = reg
    for (name, _v), spec in _PARAM_DOC_REGISTRY.catalog.items():
        if name == block_id:
            return spec
    return None


def _extract_params_section(description: str) -> str:
    """Pull the '== Params ==' block out of a block description (where rich
    human-written param semantics live, e.g. process_history's object_name).
    Returns "" if no such section."""
    if not description:
        return ""
    lines = description.split("\n")
    out: list[str] = []
    capturing = False
    for ln in lines:
        if ln.strip().startswith("== ") and "Params" in ln:
            capturing = True
            continue
        if capturing and ln.strip().startswith("== "):
            break  # next section
        if capturing:
            out.append(ln)
    return "\n".join(out).strip()


def _build_pending_param_doc_md(block_id: str) -> str:
    """Item 3 (ENABLE_CONSTRUCT_PARAM_DOC): render the param doc for the block
    the agent is about to construct, so it fills params from the spec — not from
    memory of the pick round (the SLASH-13 object_name blind-fill root cause).

    Prefer the description's '== Params ==' section (rich semantics); fall back
    to structured param_schema. Bounded length (lean-catalog discipline)."""
    spec = _get_block_spec(block_id)
    if not spec:
        return ""
    lines = [f"== PARAM DOC: {block_id} (fill its params from THIS, not memory) =="]
    section = _extract_params_section(spec.get("description") or "")
    if section:
        lines.append(section[:1400])
        return "\n".join(lines)
    # fallback: structured param_schema
    ps = spec.get("param_schema") or {}
    props = ps.get("properties") or {}
    if not props:
        return ""
    required = set(ps.get("required") or [])
    for name, p in list(props.items())[:25]:
        t = p.get("type") or "?"
        req = ", required" if name in required else ""
        enum = p.get("enum")
        desc = p.get("description") or ""
        extra = (f" enum={enum}" if enum else "") + (f" — {desc}" if desc else "")
        lines.append(f"  {name} ({t}{req}){extra[:140]}")
    return "\n".join(lines)


def _build_subphase_context_md(
    subphase: str | None,
    pipeline: PipelineJSON,
    phase: dict,
    state: dict | None,
) -> str:
    """Router — emit the context block tailored to the current sub-phase.

    pick      → flow tree + terminal cols (decide next block)
    construct → upstream output cols + sample (fill params from real data)
    tune      → node current params + upstream cols (fix the right thing)

    Returns "" for unknown sub-phase so callers fall back to the legacy
    compact snapshot.
    """
    exec_trace = (state or {}).get("exec_trace") or {}
    by_id = {n.id: n for n in pipeline.nodes}

    if subphase == "pick":
        lines = ["== SUB-PHASE: pick_block =="]
        lines.append(_build_flow_tree_md(pipeline, exec_trace))
        lines.append("")
        lines.append(
            "You're choosing the NEXT block. Pick one whose inputs the "
            "terminal cols above can satisfy. Don't guess columns you can't "
            "see — inspect_node_output(<terminal>) if you need the full sample."
        )
        return "\n".join(lines)

    if subphase == "construct":
        committed = _find_committed_block(state)
        pending_nid = (state or {}).get("v30_pending_node_id")
        lines = ["== SUB-PHASE: construct_node =="]
        if committed:
            lines.append(
                f"You committed to {committed}. add_node it, then connect upstream."
            )
            if is_construct_param_doc_enabled():
                pdoc = _build_pending_param_doc_md(committed)
                if pdoc:
                    lines.append("")
                    lines.append(pdoc)
        # DATA AVAILABLE = every node already PREVIEWED (has cols in exec_trace),
        # excluding the node currently being built (pending_nid). This is the
        # set of columns the new node can read FROM. Listing all previewed
        # nodes (not just canvas "terminals") avoids the earlier bug where a
        # freshly add_node'd, unconnected node showed up as its own upstream.
        previewed = [
            n.id for n in pipeline.nodes
            if n.id != pending_nid and _node_cols(exec_trace, n.id)
        ]
        if previewed:
            lines.append("")
            lines.append("== DATA AVAILABLE ON CANVAS (connect FROM one of these) ==")
            for nid in previewed:
                node = by_id.get(nid)
                bid = node.block_id if node else "?"
                lines.extend(_build_node_data_md(
                    exec_trace, nid, bid, sample_cap=_SAMPLE_CAP_CONSTRUCT,
                ))
            lines.append(
                "Fill add_node params using ONLY columns listed above. If the "
                "column you need is NOT present, add a transform (block_select / "
                "block_pluck) to produce it first — don't guess a column name."
            )
        else:
            lines.append(
                "(no previewed upstream yet — inspect_node_output on a source "
                "node to see its columns before filling params)"
            )
        return "\n".join(lines)

    if subphase == "tune":
        lines = ["== SUB-PHASE: tune =="]
        # Current node = the most recently mutated logical id, else last node.
        cur_nid = (state or {}).get("v30_pending_node_id") or (
            pipeline.nodes[-1].id if pipeline.nodes else None
        )
        cur_node = by_id.get(cur_nid) if cur_nid else None
        if cur_node is not None:
            params_str = ", ".join(
                f"{k}={v!r}" for k, v in (cur_node.params or {}).items()
            )[:200]
            lines.append(
                f"== NODE {cur_node.id} [{cur_node.block_id}] CURRENT params =="
            )
            lines.append(f"  {params_str or '(no params set)'}")
            if is_construct_param_doc_enabled():
                pdoc = _build_pending_param_doc_md(cur_node.block_id)
                if pdoc:
                    lines.append("")
                    lines.append(pdoc)
            # Upstream of cur_node (the source for its column values).
            ups = [e.from_.node for e in pipeline.edges if e.to.node == cur_nid]
            if ups:
                lines.append("== UPSTREAM cols (valid values for your params) ==")
                for up in ups:
                    upnode = by_id.get(up)
                    bid = upnode.block_id if upnode else "?"
                    lines.extend(_build_node_data_md(
                        exec_trace, up, bid, sample_cap=_SAMPLE_CAP_CONSTRUCT,
                    ))
        lines.append(
            "set_param to fix, run_verifier when ready, or commit_pick to "
            "chain a transform that produces a column you're missing."
        )
        return "\n".join(lines)

    return ""


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

    # Item 1 (ENABLE_NEXT_MEMO): surface the agent's own plan from last round at
    # the very top, so multi-block intent (filter THEN chart) survives across the
    # otherwise-stateless rounds — the spc-cpk "forgot to add the chart" fix.
    if state and is_next_memo_enabled():
        memo = state.get("v30_next_memo")
        if memo:
            lines.append(f"▶ YOUR PLAN (what you said you'd do next): {memo}")
            lines.append("")

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
            elif result in {"validation_error", "failed", "error"}:
                em = (vr.get("error_message") or "")[:200]
                lines.append(f"  → executor error: {em}")
                lines.append(
                    f"  → 修 params (常見：param name 寫錯, e.g. 'op' 應為 'operator') "
                    f"或先 inspect_block_doc 看正確 param schema。"
                )
            elif "orphan" in result:
                lines.append(
                    f"  → block 在 canvas 上但沒 connect 上游。"
                    f"用 connect() 接到 source node 的 output port。"
                )
            missing = vr.get("missing_for_phase") or []
            if missing:
                lines.append("  ** NEXT STEP (deterministic hint) **:")
                for i, m in enumerate(missing[:3], 1):
                    lines.append(f"    {i}. {m}")
            if wp:
                lines.append(f"  blocks that WOULD pass: {wp[:8]}")
                lines.append("  → switch to one of these; don't retry the rejected block.")
            lines.append("")

    # Round 3 (2026-06-12): ENABLE_RICH_CANVAS_SNAPSHOT — replace the bare
    # canvas with a sub-phase-tailored context block that surfaces upstream
    # output columns + sample, so construct/tune rounds fill params from real
    # data instead of guessing. See docs/agent-subphase-prompt-design.html.
    rich_on = False
    try:
        from python_ai_sidecar.feature_flags import is_rich_canvas_snapshot_enabled
        rich_on = is_rich_canvas_snapshot_enabled()
    except ImportError:
        rich_on = False
    subphase = (state or {}).get("v30_subphase") if state else None
    rich_md = (
        _build_subphase_context_md(subphase, pipeline, phase, state)
        if rich_on else ""
    )
    if rich_md:
        lines.append(rich_md)
        lines.append("")
    else:
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
    lines.append(
        "Respond with EXACTLY ONE tool_use block (no plain text). "
        "If the phase goal is achieved → call **phase_complete** (with a "
        "short rationale). If you need verifier structural check first → "
        "call **run_verifier**. Plain text responses ('Phase done', "
        "'已完成', etc.) are dropped by the graph and the prompt will "
        "repeat — wasting your round budget."
    )
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
    # v30.18 (2026-05-18): SOLUTIONS section removed — its "fast-forward N
    # phases" advertisement was misleading (didn't apply same-kind guard,
    # promoted spc_panel for multi-chart cases where it can only produce 1
    # SPC chart). Agent now evaluates candidates from AVAILABLE BLOCKS +
    # inspect_block_doc per system prompt principle (see _SYSTEM).
    # _build_oneblock_solutions_section is kept as dead code for future
    # A/B testing.

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
            # v30.18: data_empty badge — filter produced 0 rows from a
            # non-empty upstream. Downstream count=0 / verdict=fail is
            # legitimate; agent should NOT redo upstream.
            badge = ""
            if extracted.get("data_empty"):
                badge = "  [data_empty: filter 拿到 0 rows (上游非空); 視為合法空結果]"
            lines.append(
                f"      → {node} [{block}]  {summary[:120]}{ex_str}{badge}"
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

    # 2026-06-17 (ENABLE_PRESENTATION_LOOKAHEAD): downstream input-contract hint
    # resolved up front by resolve_presentation_contracts_node. Surfaced right
    # after the phase goal so the handling agent aims at a concrete output shape
    # (what the present block needs) instead of a vague "transform".
    contract = (state.get("v30_phase_contracts") or {}).get(phase.get("id"))
    if contract:
        lines.append(contract)
        lines.append("")

    # v30.20 (2026-05-19) — verifier reject feedback. Build-time verifier
    # now only emits 3 result kinds: covers mismatch / validation_error /
    # orphan. No more LLM-judge reject (moved to runtime).
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
        elif result in {"validation_error", "failed", "error"}:
            em = (vr.get("error_message") or "")[:200]
            lines.append(f"  → executor error: {em}")
            lines.append(
                f"  → fix params (常見：param name 寫錯，e.g. 'op' 應為 'operator')，"
                f"或先 inspect_block_doc 看正確 param schema。"
            )
        elif "orphan" in result:
            lines.append(
                f"  → block 已加入 canvas 但沒 connect 上游。"
                f"用 connect(from_node, from_port, to_node, to_port) 接上。"
            )
        missing = vr.get("missing_for_phase") or []
        if missing:
            lines.append("  ** NEXT STEP (deterministic hint) **:")
            for i, m in enumerate(missing[:2], 1):
                lines.append(f"    {i}. {m}")
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

    # v30.19 (Q2 follow-up C): MATCHING BLOCKS section — narrows the
    # AVAILABLE BLOCKS to those whose covers includes phase.expected, so
    # agent at pick sub-phase doesn't try verdict blocks for alarm phase
    # (e.g. block_threshold in p4 alarm).
    matching = _build_matching_blocks_section(phase.get("expected"), phase.get("goal"))
    if matching:
        lines.append(matching)
        lines.append("")
    # AVAILABLE BLOCKS catalog (full list — fallback if matching is empty
    # or agent wants the broader picture).
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
    """Anthropic tool-use schema for v30 tools.

    ENABLE_ATOMIC_ADD_CONNECT (2026-06-12) adds an optional ``upstream`` field
    to ``add_node`` so the agent can atomically add + connect in one tool call
    (saves ~1 LLM round per node). Flag off ⇒ field omitted from schema and
    description so legacy two-step flow stays the only path.
    """
    try:
        from python_ai_sidecar.feature_flags import is_atomic_add_connect_enabled
        atomic_on = is_atomic_add_connect_enabled()
    except ImportError:
        atomic_on = False

    # B3 (2026-07-04): every canvas-mutating tool carries an optional
    # one-line `reason` — the Agent Console renders it as the step's 「理由」.
    # Stripped before execution (see exec_args in the dispatcher).
    _REASON_PROP = {
        "type": "string",
        "description": "一句話(≤30字)：為什麼做這一步",
    }
    add_node_props: dict[str, Any] = {
        "block_name": {"type": "string"},
        "block_version": {"type": "string", "default": "1.0.0"},
        "params": {"type": "object"},
        "reason": _REASON_PROP,
    }
    add_node_desc = (
        "Add a node to the pipeline canvas. `block_name` MUST exactly match "
        "one of the block names from the catalog (list_blocks). "
        "Control-flow tools (commit_pick, abort_node, abort_phase, "
        "remove_node, run_verifier, phase_complete) are NOT blocks — call "
        "them as their own tool_use, NEVER as add_node(block_name='<tool>')."
    )
    if atomic_on:
        add_node_props["upstream"] = {
            "type": "array",
            "description": (
                "Optional. List of upstream connections to atomically create "
                "with this node. Each item: {src_node: str, src_port?: str "
                "(default 'data'), dst_port?: str (auto-detected from block's "
                "first input port if omitted)}."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "src_node": {"type": "string"},
                    "src_port": {"type": "string", "default": "data"},
                    "dst_port": {"type": "string"},
                },
                "required": ["src_node"],
            },
        }
        add_node_desc += (
            " For non-source blocks (filter, chart, etc.), prefer passing "
            "`upstream=[{src_node: 'nK'}]` in the same call — saves a round vs "
            "calling add_node then connect separately."
        )
    _specs: list[dict[str, Any]] = [
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
            "description": (
                "Get doc for a block. Default section='summary' returns the "
                "lean doc (description + Inputs/Outputs/Parameters/When-to-invoke, "
                "drops Examples) — ~22-25% smaller, usually enough. Pass "
                "section='full' when picking a tricky block or you need a "
                "concrete example to copy from."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string"},
                    "section": {
                        "type": "string",
                        "enum": ["summary", "full"],
                        "default": "summary",
                        "description": "'summary' lean (default) | 'full' includes Examples + full markdown",
                    },
                },
                "required": ["block_id"],
            },
        },
        {
            "name": "add_node",
            "description": add_node_desc,
            "input_schema": {
                "type": "object",
                "properties": add_node_props,
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
                    "reason": _REASON_PROP,
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
                    "reason": _REASON_PROP,
                },
                "required": ["node_id", "key", "value"],
            },
        },
        {
            "name": "remove_node",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "Remove a node + its edges."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}, "reason": _REASON_PROP},
                "required": ["node_id"],
            },
        },
        # v30.19 (2026-05-19) — signal tools for per-node lifecycle (Q2).
        # No-op tools; dispatcher reads name to transition v30_subphase.
        {
            "name": "commit_pick",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "v30.19 — leaves pick sub-phase. Use after you've decided which block to add. "
                "Pass `block_id` you'll add next + 1-line reasoning."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "block_id": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
                "required": ["block_id"],
            },
        },
        {
            "name": "abort_node",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "v30.19 — back to pick_block sub-phase. Use ONLY if you picked the wrong "
                "BLOCK and need to choose a different block_name.\n"
                "⚠ DOES NOT remove the node from canvas. Only resets the sub-phase pointer "
                "so you can commit_pick a different block.\n"
                "Wrong tool for these cases (use these instead):\n"
                "  - wrong block: abort_node here is OK, but call remove_node first to drop the dead node.\n"
                "  - just want to fix params on the same block: use set_param(node_id, key, value) — "
                "do NOT abort_node + add_node again, that creates a duplicate ghost node.\n"
                "  - block returned error and you want to retry with new params: use set_param to fix, "
                "then run_verifier or phase_complete; only abort_node if you decide a different block "
                "is needed entirely."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": [],
            },
        },
        {
            "name": "abort_phase",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "v30.19 — give up on current phase. Use only after multiple sub-state retries failed. "
                "Escalates to phase_revise."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
        {
            "name": "run_verifier",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "v30.19 — leaves tune sub-phase to phase verifier. Use when you're done tuning params."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "phase_complete",
            "description": (
                "Control-flow tool (NOT a block — call directly, do not pass to add_node). "
                "Declare current phase done — verifier checks; if mismatch, you must continue rounds."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"rationale": {"type": "string"}},
                "required": ["rationale"],
            },
        },
    ]

    # Item 1 (ENABLE_NEXT_MEMO, 2026-06-13): every canvas mutation must declare
    # `next` — a one-line plan for the NEXT step toward the phase deliverable.
    # Surfaced at the top of the following round so multi-block intent (filter
    # THEN chart) survives across rounds (the spc-cpk "forgot to add chart"
    # root cause). Marked required so the function-calling model fills it; if
    # the phase is actually done, the agent calls phase_complete (no mutation).
    if is_next_memo_enabled():
        _MUTATION_TOOLS = {"add_node", "set_param", "connect", "remove_node"}
        for _spec in _specs:
            if _spec["name"] in _MUTATION_TOOLS:
                _sch = _spec["input_schema"]
                _sch["properties"]["next"] = {
                    "type": "string",
                    "description": (
                        "REQUIRED. One line: your planned NEXT step toward this "
                        "phase's deliverable (e.g. \"add block_line_chart from n3, "
                        "x=eventTime y=value series=name\"). If the deliverable is "
                        "ALREADY complete, do NOT mutate — call phase_complete instead."
                    ),
                }
                if "next" not in _sch["required"]:
                    _sch["required"] = list(_sch["required"]) + ["next"]
    return _specs


# 2026-06-10 (KIMI K2.5 on OpenRouter fix) — when the model wants to end the
# current phase but replies in plain text ("Phase p1 complete. ...") instead
# of calling phase_complete, _extract_tool_call returned None and graph just
# replayed the same prompt next round. KIMI then guessed and re-added the
# same node (verified via trace 20260610-142738). Anthropic's tool-use
# guarantees this never fires; for tool-following-lax providers we
# synthesize the missing tool call. Conservative regex — must match the
# observed "phase ... complete/done/finished/goal achieved" intent shape
# exactly. Generic text like "I think we're done" won't trigger.
_PHASE_DONE_INTENT_RE = re.compile(
    # English: "phase complete/done/finished" with up to ~6 words between
    # (covers "phase has been completed", "phase was finished successfully").
    r"phase\s*(?:p\d+\s*)?(?:\w+\s+){0,6}?(?:complete|completed|done|finished)\b"
    r"|phase\s+goal\s+(?:is\s+)?(?:achieved|met|reached|satisfied)\b"
    # Chinese: "Phase pN 已完成" / "phase 完成" / "已建立...節點" type signals
    # for completion. KIMI on OpenRouter loves "已完成" + "等待進入下一 phase".
    r"|phase\s*p?\d*\s*已?完成"
    r"|已完成.*下[一個]?\s*phase",
    re.IGNORECASE,
)


def _extract_tool_call(resp: Any) -> dict[str, Any] | None:
    """Extract first tool_use block from LLM response. Returns None if none.
    Returns {name, args, id} where id is the tool_use_id needed for the
    matching tool_result in the next user message.

    Fallback (2026-06-10): if response has NO tool_use but text clearly
    signals phase completion intent, synthesize a phase_complete tool_use
    so the verifier can advance instead of the graph replaying the prompt
    (which sends KIMI into a duplicate-add_node spiral). Text is captured
    as the rationale, truncated to 500 chars.
    """
    content = getattr(resp, "content", None) or []
    if not isinstance(content, list):
        return None
    text_parts: list[str] = []
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
        elif btype == "text":
            text = getattr(blk, "text", None) or (blk.get("text") if isinstance(blk, dict) else None)
            if text:
                text_parts.append(str(text))
    if text_parts:
        full_text = " ".join(text_parts).strip()
        if _PHASE_DONE_INTENT_RE.search(full_text):
            logger.info(
                "_extract_tool_call: synthesized phase_complete from "
                "tool-less text response (likely KIMI/non-Anthropic provider)"
            )
            return {
                "name": "phase_complete",
                "args": {"rationale": full_text[:500]},
                "id": "synth_phase_complete",
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
        # v30.21 (2026-05-19) — surface the FULL DB-backed Markdown doc
        # body (When-to-use / Inputs / Outputs / Examples / 前置依賴),
        # not just param names. Prior digest threw away ~95% of the doc
        # before the LLM saw it, leaving agent guessing params + missing
        # critical upstream dependency hints. See feedback_no_case_rule_in_prompt.md
        # — the right place for usage principles is the per-block doc,
        # not the system prompt.
        bid = result.get("block_id") or "(?)"
        cat = result.get("category") or "?"
        desc = (result.get("description") or "").strip()
        param_lines = _fmt_param_schema_lines(result.get("param_schema") or {})
        io_lines = _fmt_io_ports(
            result.get("input_schema") or [], result.get("output_schema") or [],
        )
        col_lines = _fmt_column_docs(result.get("column_docs") or [])

        out = f"got block_doc for {bid} (cat={cat}):\n\n=== DOC ===\n{desc}\n"
        if io_lines:
            out += f"\n=== INPUT / OUTPUT PORTS ===\n{io_lines}\n"
        out += (
            f"\n=== STRICT PARAM SCHEMA (params key 必須一字不差) ===\n"
            f"{param_lines}\n"
        )
        if col_lines:
            out += f"\n=== UPSTREAM COLUMN HINTS ===\n{col_lines}\n"
        out += (
            "\n(已 inspect 過; 除非 params 改動，不要重複 inspect。"
            "重點看「不適用情境 / 必要欄位 / 前置依賴」section 避免常見錯誤。)"
        )
        # Cap at 6K chars — leaves headroom in the LLM prompt window while
        # preserving the full body for typical blocks (~2-5K each).
        if len(out) > 6000:
            out = out[:5900] + "\n... [truncated to 6K chars]"
        return out
    if tool == "inspect_node_output":
        nid = result.get("node_id")
        rows = result.get("rows")
        ports = [k for k in result if k not in {"node_id", "status", "rows", "error"}]
        # Surface ALL column names + one real sample row. The old code showed
        # only cols[:8] (truncated) and never rendered the sample values at all
        # — so the agent inspected to find e.g. is_ooc/status, never saw them
        # (hidden past col #8), and re-inspected in a loop burning the phase's
        # round budget (ooc-pareto handover root cause, 2026-06-13). Values are
        # per-field length-capped so nested APC/DC dicts don't blow up the prompt.
        sample_hint = ""
        for port in ports:
            blob = result.get(port) or {}
            if isinstance(blob, dict):
                sr = blob.get("sample_rows") or []
                cols = blob.get("all_columns") or blob.get("columns") or []
                if cols:
                    sample_hint = f" cols={list(cols)}"
                    if sr and isinstance(sr[0], dict):
                        preview = {
                            k: str(v)[:40] for k, v in list(sr[0].items())[:40]
                        }
                        sample_hint += (
                            " sample="
                            + json.dumps(preview, ensure_ascii=False)[:800]
                        )
                    break
        positive = ""
        if isinstance(rows, int) and rows >= 1:
            positive = (
                " -- has data; if this satisfies the phase goal, call the "
                "phase_complete TOOL directly next round (do NOT do "
                "add_node(block_name='phase_complete') — phase_complete is "
                "a control-flow tool, not a block)"
            )
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


# ─────────────────────────────────────────────────────────────────────
# v30.21 (2026-05-19) — inspect_block_doc digest helpers.
# Used by _make_result_digest to render full Markdown + ports + params
# instead of a bare param-name list. Was: agent saw 429 chars of param
# schema only; now sees ~2.5K chars covering When-to-use / 前置依賴 /
# Examples — the actual usage guidance the user wrote in block_docs DB.
# ─────────────────────────────────────────────────────────────────────


def _terminal_block_matches_expected(
    pipeline: PipelineJSON,
    expected: str,
    registry: Any,
) -> bool:
    """True iff the canvas has at least one terminal node whose block's
    `covers_output` includes `expected`.

    Used by ENABLE_AUTO_VERIFIER to decide if the phase looks "done" — a
    chart phase with a terminal chart block, a raw_data phase with a
    terminal MCP/find block, etc. Returns False conservatively if any
    metadata lookup fails.
    """
    if not pipeline.nodes or not expected or registry is None:
        return False
    try:
        outgoing = {e.from_.node for e in pipeline.edges}
        terminals = [n for n in pipeline.nodes if n.id not in outgoing]
        if not terminals:
            return False
        from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
            _resolve_covers,
        )
        for n in terminals:
            spec = registry.get_spec(n.block_id, n.block_version) or {}
            covers = _resolve_covers(spec, kind="output")
            if expected in covers:
                return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("_terminal_block_matches_expected failed: %s", exc)
        return False
    return False


def _should_auto_verify(
    state: BuildGraphState,
    phase: dict,
    tool_name: str,
    action_result: dict | None,
    recent_actions_history: list[dict],
    transient_pipeline: PipelineJSON,
    registry: Any,
) -> bool:
    """ENABLE_AUTO_VERIFIER gate — decide if the round should auto-trigger
    the verifier without waiting for agent's explicit run_verifier.

    Trigger conditions (all must hold):
      1. Flag on
      2. Tool that just ran was a canvas mutation (add_node / connect)
      3. Mutation succeeded (no error in action_result)
      4. Phase's expected block kind is satisfied by some terminal block
         on the canvas (chart phase ⇒ terminal chart block, etc.)
      5. Agent looks "decisive": no inspect_* tool calls in the most
         recent 2 actions (still-exploring builds should not auto-verify)

    Returns False conservatively on any error.
    """
    if not is_auto_verifier_enabled():
        return False
    if tool_name not in {"add_node", "connect"}:
        return False
    if action_result and "error" in action_result:
        return False
    expected = (phase.get("expected") or "").strip()
    if not _terminal_block_matches_expected(transient_pipeline, expected, registry):
        return False
    # "Decisive" check: the last 2 actions in history (BEFORE this round's
    # append) should not include inspect_* — that signals the agent was
    # still gathering info and shouldn't be force-verified.
    last_2 = recent_actions_history[-2:] if recent_actions_history else []
    for a in last_2:
        tool = (a.get("tool") if isinstance(a, dict) else "") or ""
        if tool.startswith("inspect_"):
            return False
    return True


def _coalesce_preview_error(pv: dict) -> str | None:
    """Pull a single error string out of a toolset.preview() result.

    preview() returns `error` (singular string) when a block's executor
    raises BlockExecutionError, and `errors` (plural list) when the
    PipelineValidator rejects the subgraph. Coalesce both so downstream
    (snapshot -> phase_verifier -> agent feedback) always gets the real
    reason instead of "(no error message captured)".
    """
    _err = pv.get("error")
    if _err:
        return _err
    _errs = pv.get("errors")
    if isinstance(_errs, list) and _errs:
        parts = []
        for e in _errs[:3]:
            if isinstance(e, dict):
                msg = e.get("message") or e.get("hint") or ""
                code = e.get("code") or e.get("rule") or ""
                parts.append(f"[{code}] {msg}" if code else msg)
            else:
                parts.append(str(e))
        return " | ".join(p for p in parts if p) or None
    return None


async def _fresh_terminal_snapshot(
    toolset: Any, pipeline: PipelineJSON, node_id: str, round_n: int,
) -> dict | None:
    """2026-06-25 (hardening #3): re-preview a node NOW and build a verifier
    snapshot capturing the CURRENT status + error.

    Used by the run_verifier / phase_complete path: those are signal tools
    (no mutation), so no auto-preview ran this round. Without a fresh preview
    the verifier reads a stale or absent exec_trace entry — a failing terminal
    then surfaces "(no error message captured)" and the agent loops blind
    (observed: block_sort flailed 44 rounds with error=null, 2026-06-25).
    """
    pv = await toolset.preview(node_id=node_id, sample_size=5)
    blk_id = None
    for n in pipeline.nodes:
        if n.id == node_id:
            blk_id = n.block_id
            break
    return {
        "logical_id": node_id,
        "real_id": node_id,
        "block_id": blk_id,
        "rows": pv.get("rows"),
        "status": pv.get("status"),
        "error": _coalesce_preview_error(pv),
        "after_cursor": round_n,
    }


def _find_canvas_terminal(
    pipeline: PipelineJSON, exec_trace: dict[str, dict],
    expected: str = "",
    registry: Any = None,
) -> tuple[str | None, dict | None]:
    """Find canvas terminal — node with no outgoing edges.
    Used when agent calls run_verifier / phase_complete to point verifier
    at the right node (signal tools aren't mutations).

    v30.23 (2026-05-20) — multi-terminal awareness: when canvas has
    multiple terminals (e.g. phase built parallel branches like
    probability_plot + cpk for a chart phase), prefer the terminal
    whose block.covers_output includes `expected`. Side-branch blocks
    (cpk in chart phase) get naturally ignored — phase passes on the
    matching terminal, side branches stay as bonus output.

    Falls back to latest-added terminal if no covers match (verifier
    will reject with covers mismatch and surface would_pass hint).

    Returns (logical_id, preview_blob) or (None, None) for empty canvas.
    """
    if not pipeline.nodes:
        return None, None
    outgoing = {e.from_.node for e in pipeline.edges}
    terminals = [n for n in pipeline.nodes if n.id not in outgoing]
    if not terminals:
        # All nodes have outgoing edges (cycle) — return last
        last = pipeline.nodes[-1]
        return last.id, None

    def _build_preview(node_id: str) -> dict | None:
        snap = exec_trace.get(node_id) or {}
        sample = snap.get("sample")
        if sample is not None:
            return {"data": {"type": "dataframe", "rows": [sample]}}
        return None

    # Prefer terminal whose covers_output includes phase.expected.
    # Walk reverse-add so latest matching wins (more recent = more relevant).
    if expected and registry is not None:
        from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
            _resolve_covers,
        )
        for n in reversed(terminals):
            spec = registry.get_spec(n.block_id, n.block_version) or {}
            covers = _resolve_covers(spec, kind="output")
            if expected in covers:
                logger.info(
                    "_find_canvas_terminal: %s matches expected=%s "
                    "(picked over %d other terminal(s))",
                    n.id, expected, len(terminals) - 1,
                )
                return n.id, _build_preview(n.id)

    # Fallback: latest-added terminal (covers will likely mismatch,
    # verifier emits would_pass hint for agent to course-correct)
    last = terminals[-1]
    return last.id, _build_preview(last.id)


def _fmt_io_ports(input_schema: list[dict], output_schema: list[dict]) -> str:
    """Format input + output ports concisely. Empty schemas → empty string
    (caller skips the section)."""
    lines: list[str] = []
    if input_schema:
        lines.append("inputs:")
        for p in input_schema:
            port = p.get("port", "?")
            ptype = p.get("type", "?")
            req = "required" if p.get("required", True) else "optional"
            lines.append(f"  {port:<10} ({ptype}, {req})")
    if output_schema:
        lines.append("outputs:")
        for p in output_schema:
            port = p.get("port", "?")
            ptype = p.get("type", "?")
            lines.append(f"  {port:<10} ({ptype})")
    return "\n".join(lines)


def _fmt_param_schema_lines(ps: dict) -> str:
    """Format param schema as one-line-per-param: name (type, REQ/opt) default+enum."""
    required = ps.get("required") or []
    props = ps.get("properties") or {}
    lines: list[str] = []
    for pname, pspec in list(props.items())[:20]:
        ptype = pspec.get("type", "?")
        req = "REQUIRED" if pname in required else "opt"
        default = pspec.get("default")
        enum = pspec.get("enum")
        extra = ""
        if default is not None:
            extra += f" default={default!r}"
        if enum:
            extra += f" enum={enum}"
        lines.append(f"  {pname} ({ptype}, {req}){extra}")
    return "\n".join(lines) or "  (no params)"


def _fmt_column_docs(column_docs: list[dict]) -> str:
    """Format column_docs hints (best/ok/warn tags). Empty → empty string."""
    if not column_docs:
        return ""
    lines: list[str] = ["(when picking the column param, prefer [best] tags; check [warn] for gotchas)"]
    for c in column_docs[:12]:
        name = c.get("name", "?")
        tag = c.get("tag", "")
        desc = (c.get("desc") or "")[:90]
        tag_str = f"[{tag}] " if tag else ""
        lines.append(f"  {tag_str}{name:<22} {desc}")
    return "\n".join(lines)


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


# ─────────────────────────────────────────────────────────────────────
# v30.19 (2026-05-19) — Q2: per-node lifecycle sub-state machine.
#
# Sub-state transitions enforce the "pick → construct → tune → verify"
# lifecycle per added block. Tools available per sub-state are filtered
# so agent structurally can't skip steps (e.g. add_node without commit_pick
# first, or connect-after-add without exiting pick first).
# ─────────────────────────────────────────────────────────────────────

# Tool subset per sub-phase. Names match _build_tool_specs entries.
_TOOLS_BY_SUBPHASE: dict[str, set[str]] = {
    "pick": {
        "inspect_node_output", "inspect_block_doc",
        "commit_pick", "abort_phase",
    },
    "construct": {
        "add_node", "connect", "abort_node", "abort_phase",
        # v30.22: allow inspect during construct so agent can sanity-check
        # upstream output shape before connecting (avoids hallucination of
        # column names — see R3 alarm phase root cause analysis).
        "inspect_node_output", "inspect_block_doc",
    },
    "tune": {
        "set_param", "run_verifier", "abort_node", "abort_phase",
        # v30.22: allow agent to chain another block from tune (e.g. after
        # adding filter and tuning, commit_pick step_check to continue
        # building the count+compare chain).
        "commit_pick",
        "inspect_node_output", "inspect_block_doc",
    },
    # refine isn't an LLM sub-state — deterministic transition only.
}


def _filter_tool_specs_for_subphase(
    all_specs: list[dict], subphase: str | None,
) -> list[dict]:
    """Return only tool specs allowed in current sub-phase.
    Unknown sub-phase or None → return all (backward compat for v30.18
    builds that don't set sub_phase).

    When ENABLE_AUTO_SIGNAL is on, the pick sub-phase additionally allows
    `add_node` (auto-commit shortcut — saves one LLM round per block pick).
    """
    if not subphase or subphase not in _TOOLS_BY_SUBPHASE:
        return all_specs
    allowed = set(_TOOLS_BY_SUBPHASE[subphase])
    if subphase == "pick":
        try:
            from python_ai_sidecar.feature_flags import is_auto_signal_enabled
            if is_auto_signal_enabled():
                allowed = allowed | {"add_node"}
        except Exception:
            pass
    return [s for s in all_specs if s.get("name") in allowed]


def _build_subphase_hint(subphase: str | None, state: BuildGraphState) -> str:
    """Prepend a short line telling the agent which sub-phase it's in.
    Helps the LLM understand why some tools are missing."""
    if not subphase:
        return ""
    if subphase == "pick":
        try:
            from python_ai_sidecar.feature_flags import is_auto_signal_enabled
            auto = is_auto_signal_enabled()
        except Exception:
            auto = False
        if auto:
            return (
                "== SUB-PHASE: pick_block ==\n"
                "Decide which block to add next. Inspect candidates (inspect_block_doc),\n"
                "look at upstream output (inspect_node_output). When ready, either:\n"
                "  - call **commit_pick(block_id, reasoning)** to commit your choice, OR\n"
                "  - go straight to **add_node(block_name, params)** — auto-commits "
                "the pick and adds the block in one step."
            )
        return (
            "== SUB-PHASE: pick_block ==\n"
            "Decide which block to add next. Inspect candidates (inspect_block_doc),\n"
            "look at upstream output (inspect_node_output). When ready, call\n"
            "**commit_pick(block_id, reasoning)** — you cannot add_node from this\n"
            "sub-phase, only commit your choice."
        )
    if subphase == "construct":
        pending = state.get("v30_pending_block")
        return (
            f"== SUB-PHASE: construct_node ==\n"
            f"You committed to {pending!r}. Now add_node + connect upstream.\n"
            f"After add_node, you MUST connect() before exit. If you change your\n"
            f"mind, abort_node() to go back to pick_block.\n"
            f"You can also inspect_node_output(upstream_id) here to sanity-check\n"
            f"the upstream shape before guessing column names."
        )
    if subphase == "tune":
        return (
            "== SUB-PHASE: tune_or_chain_or_verify ==\n"
            "Options now:\n"
            "  - set_param(node_id, key, value) — adjust params on current block\n"
            "  - commit_pick(block_id) — chain ANOTHER block (e.g. you added\n"
            "    filter, now want step_check downstream). Goes back to construct.\n"
            "  - inspect_node_output(node_id) — sanity-check current terminal\n"
            "    output before declaring done\n"
            "  - **run_verifier()** — phase is done, trigger verifier check\n"
            "  - abort_node / abort_phase — bail out\n\n"
            "**重要**: 多 block phase (如 OOC count = filter→step_check) 要在\n"
            "chain 完整後再 run_verifier，不要過早 verify。"
        )
    return ""


# Sub-phase transition rules — pure function of (current sub-phase, tool name).
# Returns next sub-phase or None (no change).
_TRANSITIONS: dict[tuple[str, str], str] = {
    ("pick", "commit_pick"):       "construct",
    ("pick", "abort_phase"):       "refine",
    # ENABLE_AUTO_SIGNAL (2026-06-11): allow add_node from pick to skip the
    # explicit commit_pick round. add_node lands the block in construct just
    # like commit_pick → add_node would, saving one LLM call per block pick.
    ("pick", "add_node"):          "construct",
    ("construct", "add_node"):     "construct",  # stay; expect connect next
    ("construct", "connect"):      "tune",
    ("construct", "abort_node"):   "pick",
    ("construct", "abort_phase"):  "refine",
    ("tune", "set_param"):         "tune",       # stay; allow more set_param
    ("tune", "run_verifier"):      "tune",       # stay; verifier will route out
    ("tune", "abort_node"):        "pick",
    ("tune", "abort_phase"):       "refine",
    # v30.22: chain another block from tune. agent commits to a new
    # block_id while previous one is still on canvas; goes back to
    # construct to add + connect it. Enables multi-block phases.
    ("tune", "commit_pick"):       "construct",
    # Auto-signal shortcut for chain-from-tune too: add_node directly from
    # tune means "commit a new block_id and add it" in one round.
    ("tune", "add_node"):          "construct",
}


def _next_subphase(
    current: str | None,
    tool_name: str,
    tool_args: dict | None = None,
) -> str | None:
    """Pure: compute next sub-phase or None if no transition.

    ENABLE_ATOMIC_ADD_CONNECT (2026-06-12): when add_node carries an
    `upstream` arg (and lands successfully), the connect step is already
    done in the same tool call, so we skip ``construct`` and land in
    ``tune`` directly. Saves one LLM round per node.
    """
    if not current:
        return None
    if (
        tool_name == "add_node"
        and tool_args
        and tool_args.get("upstream")
        and current in ("pick", "construct", "tune")
    ):
        return "tune"
    return _TRANSITIONS.get((current, tool_name))


# ─────────────────────────────────────────────────────────────────────
# Sentinel-tool execution shims. These tools are no-ops at the BuilderToolset
# layer — they exist purely to drive the sub-state machine. The dispatcher
# checks tool_name and updates state without going through toolset.
# ─────────────────────────────────────────────────────────────────────

_SIGNAL_TOOLS = {"commit_pick", "abort_node", "abort_phase", "run_verifier"}


def _handle_signal_tool(tool_name: str, args: dict) -> dict:
    """Return a benign ack result for signal tools so they appear successful
    in the conversation. Real effect is via sub-phase transition."""
    if tool_name == "commit_pick":
        return {
            "ok": True,
            "committed_block_id": args.get("block_id"),
            "next_subphase": "construct",
        }
    if tool_name == "abort_node":
        return {"ok": True, "back_to": "pick"}
    if tool_name == "abort_phase":
        return {"ok": True, "escalating_to": "refine"}
    if tool_name == "run_verifier":
        return {"ok": True, "running_verifier": True}
    return {"ok": True}


# v30.19 (Q2 follow-up C): MATCHING BLOCKS section — filter catalog by
# phase.expected via produces.covers_internal. Surfaces ONLY blocks
# whose covers includes phase.expected, so agent at pick sub-phase
# doesn't pull verdict blocks for alarm phase etc.
def _char_bigrams(text: str) -> set[str]:
    """Whitespace-stripped char bigrams — a cheap CJK-friendly relevance signal
    (no tokenizer needed). '機台清單' → {機台, 台清, 清單}."""
    import re as _re
    t = _re.sub(r"\s+", "", text or "")
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _goal_relevance(goal_bg: set[str], name: str, oneliner: str) -> int:
    """Overlap of the phase goal's bigrams with a block's name+oneliner. Higher
    = more relevant to THIS phase's goal (not just its expected kind)."""
    if not goal_bg:
        return 0
    return len(goal_bg & _char_bigrams((name or "") + (oneliner or "")))


def _build_matching_blocks_section(expected: str | None, goal: str | None = None) -> str:
    if not expected:
        return ""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.phase_verifier import (
        _resolve_covers,
    )
    registry = SeedlessBlockRegistry()
    registry.load()
    matches: list[tuple[str, list[str], str]] = []
    for (name, _v), spec in registry.catalog.items():
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        cov_int = _resolve_covers(spec, kind="internal")
        if expected not in cov_int:
            continue
        cov_out = _resolve_covers(spec, kind="output")
        # 1-line description from baked seed (fallback when DB doc not loaded)
        desc = (spec.get("description") or "").strip()
        import re as _re
        m = _re.search(r"== What ==\s*\n+(.+?)(?:\n\n|\n==)", desc, _re.DOTALL)
        first = (m.group(1).strip().split("\n")[0] if m else desc.split("\n", 1)[0])[:90]
        matches.append((name, cov_out, first))
    if not matches:
        return ""

    # 2026-06-18 (ENABLE_GOAL_AWARE_MATCHING): re-rank by relevance to the phase
    # GOAL (not just kind) and mark the top candidate [best fit]. Adjacent
    # same-kind phases (e.g. two raw_data: "list machines" vs "fetch per machine")
    # otherwise show identical lists and lure the agent into the wrong-phase
    # block (spc-ooc root cause). Re-ranked, never removed.
    best_fit: str | None = None
    if is_goal_aware_matching_enabled() and goal:
        goal_bg = _char_bigrams(goal)
        scored = [(_goal_relevance(goal_bg, n, f), n, c, f) for (n, c, f) in matches]
        scored.sort(key=lambda t: (-t[0], t[1]))
        matches = [(n, c, f) for (_s, n, c, f) in scored]
        if scored and scored[0][0] > 0:
            best_fit = scored[0][1]
    else:
        matches.sort(key=lambda t: t[0])

    lines: list[str] = [
        f"== MATCHING BLOCKS for phase.expected={expected} (covers match) ==",
        "(Only these block types cover this phase's expected output kind.)",
    ]
    if best_fit:
        lines.append(f"(Ranked by relevance to THIS phase's goal; **{best_fit}** "
                     f"is the best fit for this phase — others may belong to a "
                     f"different phase.)")
    for name, cov_out, first in matches[:15]:
        tag = "  [best fit for this phase]" if name == best_fit else ""
        lines.append(f"  {name}  covers_output={cov_out}  -- {first}{tag}")
    return "\n".join(lines)
