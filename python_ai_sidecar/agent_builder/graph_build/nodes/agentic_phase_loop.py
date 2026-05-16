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
7. phase 達成 -> `phase_complete(rationale)`  (系統會做 deterministic verifier 確認)

== Phase 達成判定 ==
phase.expected 決定 verifier 看什麼:
  raw_data   -> 必須有 source-category node + rows >= 1
  transform  -> 必須有 dataframe 輸出的 terminal node + rows >= 1
  verdict    -> 必須有 verdict-output block (step_check / threshold)
  chart      -> 必須有 chart-category terminal node
  table      -> 必須有 block_data_view terminal node
  scalar     -> 必須有 single-value 輸出 terminal
  alarm      -> 必須有 alert block

== 禁忌 ==
- 不要 emit JSON ops list — 用 single tool call
- 不要在沒讀過 upstream runtime schema 時憑空寫 column 名 (用 inspect 先看)
- 不要重複加同一 block 同一 params (stuck detector 會擋)
- 不要忽視 column_docs 的 [no] 警告 (e.g. 「OOC 數量?」不要用 spc_status，用 spc_summary.ooc_count)

== Param naming 嚴格規則 ==
add_node 的 `params` key 必須**100% 一字不差**從 inspect_block_doc 的 param_schema 抄過來。
**不要用同義詞替換**：
  X equipment_id  ->  block_process_history 用的是 tool_id，**不是** equipment_id
  X column_name   ->  block_filter 用的是 column，**不是** column_name
  X chart_type    ->  block_line_chart 用的是 type，**不是** chart_type
若不確定 -> 先 inspect_block_doc(block_id)，看 param_schema 列出的 EXACT param names。

== 何時 phase_complete ==
看到 add_node + auto_preview 成功 + 結果符合 phase 的 expected kind ->
**立即** call phase_complete(rationale="...")，**不要拖**。系統會跑 verifier，
若不符 expected 它會擋並告訴你下一步該做什麼。

別把所有 8 round 都拿來 inspect — 通常 inspect → add_node → preview → phase_complete 4 round 就該結束。
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
    client = get_llm_client()
    tool_specs = _build_tool_specs()

    try:
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": full_user_msg}],
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

    # Extract tool_use from response
    tool_call = _extract_tool_call(resp)
    if tool_call is None:
        logger.info("agentic_phase_loop: phase %s round %d — no tool call", pid, round_n + 1)
        return {
            "v30_phase_round": round_n + 1,
            "sse_events": [_event("phase_round", {
                "phase_id": pid, "round": round_n + 1, "max": MAX_REACT_ROUNDS,
                "no_action": True,
            })],
        }

    tool_name = tool_call["name"]
    tool_args = tool_call.get("args") or {}

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
    auto_preview_result = None
    mutating = {"add_node", "set_param", "connect", "remove_node"}
    if tool_name in mutating and "error" not in action_result:
        target_nid = action_result.get("node_id") or tool_args.get("node_id") or tool_args.get("to_node")
        if target_nid:
            try:
                pv = await toolset.preview(node_id=target_nid, sample_size=2)
                auto_preview_result = {
                    "node_id": target_nid,
                    "rows": pv.get("rows"),
                    "status": pv.get("status"),
                }
            except Exception as ex:  # noqa: BLE001
                logger.info("auto-preview %s failed: %s", target_nid, ex)

    # ── Phase complete signal? Run verifier ──────────────────────────
    phase_done = False
    verifier_result = None
    if tool_name == "phase_complete":
        verifier_result = _check_phase_done(transient.pipeline_json, phase, registry)
        phase_done = verifier_result.get("match", False)
        if not phase_done:
            logger.info(
                "agentic_phase_loop: phase %s verifier rejected complete signal: %s",
                pid, verifier_result.get("reason"),
            )
            # LLM gets feedback next round — keep round counter going
            action_result = {
                **action_result,
                "verifier_says": verifier_result,
                "_note": "phase NOT done per verifier — try more rounds",
            }

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

    state_update: dict[str, Any] = {
        "v30_phase_round": round_n + 1,
        "v30_phase_recent_actions": new_recent,
        "final_pipeline": new_pipeline_dict,
    }

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
        }),
    ]
    if auto_preview_result:
        sse_events.append(_event("phase_observation", {
            "phase_id": pid, "round": round_n + 1,
            "preview": auto_preview_result,
        }))

    if phase_done:
        # Advance to next phase
        outcomes = dict(state.get("v30_phase_outcomes") or {})
        outcomes[pid] = {
            "status": "completed",
            "completed_round": round_n + 1,
            "rationale": action_result.get("rationale") or "",
            "verifier_check": verifier_result,
        }
        state_update["v30_phase_outcomes"] = outcomes
        state_update["v30_current_phase_idx"] = idx + 1
        state_update["v30_phase_round"] = 0  # reset for next phase
        sse_events.append(_event("phase_completed", {
            "phase_id": pid, "rationale": action_result.get("rationale") or "",
        }))
        if tracer is not None:
            tracer.record_step(
                "agentic_phase_loop", status="phase_completed",
                phase_id=pid, rounds_used=round_n + 1,
                verifier=verifier_result,
            )

    if tracer is not None:
        tracer.record_step(
            "agentic_phase_loop", status="round_done",
            phase_id=pid, round=round_n + 1,
            tool=tool_name,
            action_ok="error" not in action_result,
            auto_preview=auto_preview_result,
        )

    state_update["sse_events"] = sse_events
    return state_update


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


def _build_observation_md(state: BuildGraphState, phase: dict) -> str:
    """Assemble the prompt user content for current round."""
    lines: list[str] = []

    # Phase goal (user-confirmed — must follow)
    lines.append("== CURRENT PHASE (user-confirmed; do not deviate) ==")
    lines.append(f"id: {phase.get('id')}")
    lines.append(f"goal: {phase.get('goal')}")
    lines.append(f"expected: {phase.get('expected')}")
    if phase.get("why"):
        lines.append(f"why: {phase.get('why')}")
    lines.append("")

    # All phases context
    phases = state.get("v30_phases") or []
    idx = state.get("v30_current_phase_idx", 0)
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
    """Extract first tool_use block from LLM response. Returns None if none."""
    # Anthropic SDK shape: resp.content is list of blocks; tool_use blocks
    # have .name, .input. Newer wrapper may shape it differently.
    content = getattr(resp, "content", None) or []
    if not isinstance(content, list):
        return None
    for blk in content:
        btype = getattr(blk, "type", None) or (blk.get("type") if isinstance(blk, dict) else None)
        if btype == "tool_use":
            name = getattr(blk, "name", None) or (blk.get("name") if isinstance(blk, dict) else None)
            args = getattr(blk, "input", None) or (blk.get("input") if isinstance(blk, dict) else None) or {}
            if name:
                return {"name": name, "args": dict(args) if isinstance(args, dict) else {}}
    return None


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

    # Find terminal nodes (no outgoing edges in this phase's contribution)
    incoming = {n.id for e in pipeline.edges for n in [e.to]}
    outgoing = {n.id for e in pipeline.edges for n in [e.from_]}
    terminal_ids = [n.id for n in nodes if n.id not in outgoing]

    if not terminal_ids:
        return {"match": False, "reason": "no terminal node identified"}

    # Inspect the last-added terminal (most recent build progress)
    target = nodes[-1]
    target_spec = registry.get_spec(target.block_id, target.block_version) or {}
    category = target_spec.get("category", "")
    output_types = [p.get("type") for p in (target_spec.get("output_schema") or [])]

    if expected == "raw_data":
        ok = category == "source"
        return {"match": ok, "reason": f"terminal category={category}", "got": "source" if ok else category}
    if expected == "transform":
        ok = "dataframe" in output_types
        return {"match": ok, "reason": f"terminal dataframe? {ok}", "got": output_types}
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
