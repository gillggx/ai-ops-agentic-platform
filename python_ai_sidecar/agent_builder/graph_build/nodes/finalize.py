"""finalize_node — pure code: PipelineValidator + best-effort dry-run + SSE.

DB persistence is intentionally NOT done here. The Glass Box flow's
contract is: returned pipeline is a draft on the canvas; user's explicit
"Save" click is what writes to pb_pipelines (handled by frontend's normal
save-pipeline endpoint). v2 keeps that contract — finalize only validates
and packages the final state.

Phase 10-C Fix 4: optional best-effort dry-run via PipelineExecutor.
Catches runtime issues (column not in data, simulator error, empty
result) at build time so the chat orchestrator's auto-run doesn't
surprise the user. Build status stays "finished" even if dry-run
fails — the canvas IS built; the dry-run finding flows as a separate
SSE event for the UI to surface.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.feature_flags import is_strict_phase_output_enabled
from python_ai_sidecar.pipeline_builder.block_registry import BlockRegistry
from python_ai_sidecar.pipeline_builder.executor import PipelineExecutor
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.validator import PipelineValidator
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


# Blocks with side effects — dry-run skips entirely if pipeline contains any
# (writing alarms / persisting skills mid-build is unsafe). Pure source/
# transform/chart blocks run freely.
SIDE_EFFECT_BLOCKS: frozenset[str] = frozenset({
    "block_alert",
    "block_save_pipeline",
    "block_publish_skill",
    "block_send_notification",
})

# Default dry-run timeout. 7-node SPC pipelines run ~1-2s; 10s leaves
# headroom without making finalize feel blocking.
DRYRUN_TIMEOUT_SEC = 10.0

# C2: user-visible deliverable kinds. If the plan's FINAL phase wants one of
# these but the built canvas has no terminal block covering it, the build lost
# its deliverable — surfaced as failed_missing_output (ENABLE_STRICT_PHASE_OUTPUT).
# Intermediate kinds (raw_data / transform / verdict) are excluded: they are
# legitimately consumed by a downstream presentation block, so they are often
# NOT terminal even on a correct build.
_PRESENTATION_KINDS: frozenset[str] = frozenset({"chart", "table", "scalar", "alarm"})


def _missing_deliverable_reason(
    pipeline: PipelineJSON,
    v30_phases: list[dict[str, Any]],
    registry: Any,
) -> str:
    """C2 — pure deliverable fact-check.

    Returns a human-readable reason iff the plan's FINAL phase declares a
    presentation kind (chart/table/scalar/alarm) that NO terminal block on the
    built canvas covers. Returns "" when the deliverable is satisfied, the final
    phase isn't a presentation kind, or the check can't run (fail-open — an infra
    hiccup must never mask a real build).

    Caller is responsible for gating on ENABLE_STRICT_PHASE_OUTPUT + v30 path.
    Only the plan's last phase is checked, not every presentation phase: a
    table->chart plan keeps the table NON-terminal on a correct build, so a
    per-phase check would false-positive.
    """
    if not v30_phases:
        return ""
    final_expected = (v30_phases[-1].get("expected") or "").strip()
    if final_expected not in _PRESENTATION_KINDS:
        return ""
    from python_ai_sidecar.agent_builder.graph_build.nodes.agentic_phase_loop import (
        _terminal_block_matches_expected,
    )
    try:
        if _terminal_block_matches_expected(pipeline, final_expected, registry):
            return ""
    except Exception as exc:  # noqa: BLE001 — infra hiccup must not mask a build
        logger.warning(
            "finalize_node: strict_phase_output check crashed, fail-open: %s", exc
        )
        return ""
    outgoing = {e.from_.node for e in pipeline.edges}
    terminal_ids = [n.block_id for n in pipeline.nodes if n.id not in outgoing]
    return (
        f"plan's final deliverable is '{final_expected}' but no terminal block "
        f"on the canvas covers it (terminals: {terminal_ids or 'none'})"
    )


def _compact_node_result(info: dict[str, Any]) -> dict[str, Any]:
    """Trim a node_result for trace storage. Keeps enough to render
    actual charts in the admin viewer:
      - dataframe: cols + first 20 rows (cap to keep trace size sane)
      - chart_spec (dict): full snapshot (the renderable spec)
      - bool/dict: small payload
    """
    if not isinstance(info, dict):
        return {"raw": str(info)[:200]}
    out: dict[str, Any] = {
        "status": info.get("status"),
        "rows": info.get("rows"),
        "duration_ms": info.get("duration_ms"),
    }
    err = info.get("error") or info.get("error_message")
    if err:
        out["error"] = str(err)[:200]
    preview = info.get("preview") or {}
    ports: dict[str, Any] = {}
    for port, blob in preview.items():
        if not isinstance(blob, dict):
            continue
        t = blob.get("type")
        if t == "dataframe":
            rows = blob.get("rows") or blob.get("sample_rows") or []
            ports[port] = {
                "kind": "dataframe",
                "columns": (blob.get("columns") or [])[:30],
                "total": blob.get("total"),
                "rows": rows[:20],  # keep first 20 sample rows for table preview
            }
        elif t == "dict":
            snap = blob.get("snapshot")
            if isinstance(snap, dict):
                # Keep the full snapshot so the admin viewer can render
                # the actual chart. Snapshots are usually <50KB and the
                # trace storage is on local disk — no need to summarise.
                ports[port] = {
                    "kind": "chart_spec",
                    "snapshot": snap,
                }
            else:
                ports[port] = {"kind": "dict", "value": snap}
        elif t == "bool":
            ports[port] = {"kind": "bool", "value": blob.get("value")}
        elif t == "list":
            ports[port] = {
                "kind": "list",
                "length": blob.get("length"),
                "sample": blob.get("sample"),
            }
        else:
            ports[port] = {"kind": t, "value": blob.get("value")}
    if ports:
        out["ports"] = ports
    return out


def _edge_node(v: Any) -> str | None:
    return v.get("node") if isinstance(v, dict) else v


def apply_plan_removals(pipeline: dict, removals: list) -> tuple[dict, list, list]:
    """v31.2 — deterministically remove modification-plan nodes.

    Applied AFTER all phases completed (new nodes exist) so the still-consumed
    guard sees the final topology: a node whose output still feeds any node
    OUTSIDE the removal set is protected (skipped with a reason) — this stops
    an LLM-listed shared upstream from breaking the new build. Removing a node
    also drops its dangling edges. Pure function; unit-tested.
    """
    want = {str(r.get("node_id")) for r in (removals or []) if isinstance(r, dict)}
    if not want or not isinstance(pipeline, dict):
        return pipeline, [], []
    nodes = list(pipeline.get("nodes") or [])
    edges = list(pipeline.get("edges") or [])
    node_ids = {n.get("id") for n in nodes}
    removed, skipped = [], []
    for nid in sorted(want):
        if nid not in node_ids:
            skipped.append({"node_id": nid, "reason": "node no longer exists"})
            continue
        consumers = {
            _edge_node(e.get("to"))
            for e in edges
            if _edge_node(e.get("from")) == nid
        } - want
        consumers.discard(None)
        if consumers:
            skipped.append({"node_id": nid,
                            "reason": f"仍被 {sorted(consumers)} 消費，保護不刪"})
            continue
        removed.append(nid)
    if not removed:
        return pipeline, [], skipped
    rm = set(removed)
    out = dict(pipeline)
    out["nodes"] = [n for n in nodes if n.get("id") not in rm]
    out["edges"] = [
        e for e in edges
        if _edge_node(e.get("from")) not in rm and _edge_node(e.get("to")) not in rm
    ]
    return out, removed, skipped


# F5 (2026-07-10): default names the builder stamps on fresh canvases. A
# pipeline still carrying one of these at finalize gets an LLM-suggested
# business name (user can edit at save / activate time).
_PLACEHOLDER_NAME_PREFIXES: tuple[str, ...] = (
    "New Pipeline", "Chat-built Pipeline", "Chat 自動化",
)


async def _maybe_generate_pipeline_name(
    pipeline: PipelineJSON, instruction: str
) -> None:
    """Replace a placeholder pipeline name with a short business name derived
    from the user's instruction. Fail-open: on any LLM issue fall back to the
    truncated instruction — never block or fail the build over a name."""
    name = (pipeline.name or "").strip()
    if not instruction or (name and not name.startswith(_PLACEHOLDER_NAME_PREFIXES)):
        return  # already has a real name (e.g. modify of a saved pipeline)
    flat_instr = " ".join(instruction.split())
    new_name = flat_instr[:24] or name or "未命名分析"
    try:
        from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
        resp = await asyncio.wait_for(
            get_llm_client().create(
                system=(
                    "為一條資料分析 pipeline 取名。只輸出名稱本身，不要任何解釋："
                    "繁體中文（臺灣用字，嚴禁任何簡體字，如「势/趋/监」都不可）或英文、"
                    "不超過 20 字、不加引號與標點、不用 emoji，"
                    "要讓工程師一眼看出業務用途（例：EQP-01 OOC 次數檢查）。"
                ),
                messages=[{"role": "user", "content": f"需求：{flat_instr[:400]}"}],
                max_tokens=60,
            ),
            timeout=8.0,
        )
        cand = (resp.text or "").strip().strip("「」\"'`").splitlines()[0].strip()
        if 1 < len(cand) <= 40:
            new_name = cand
    except Exception as ex:  # noqa: BLE001 — a name must never fail a build
        logger.warning("finalize: pipeline name generation failed (fallback): %s", ex)
    logger.info("finalize: pipeline named %r (was %r)", new_name, name)
    pipeline.name = new_name


async def finalize_node(state: BuildGraphState) -> dict[str, Any]:
    final_dict = state.get("final_pipeline") or state.get("base_pipeline")
    plan = state.get("plan") or []

    if final_dict is None:
        # Nothing was actually built — empty plan or all-failed.
        return {
            "status": "failed",
            "summary": "no pipeline produced",
            "sse_events": [_event("build_finalized", {
                "ok": False, "reason": "no pipeline",
            })],
        }

    # v31.2 — modification-plan removals: applied here (all phases done, new
    # nodes built) by pure function; the LLM loop never performs removals.
    removal_events: list[dict[str, Any]] = []
    _removals = state.get("v30_removals") or []
    if _removals and isinstance(final_dict, dict):
        final_dict, _removed, _skipped = apply_plan_removals(final_dict, _removals)
        if _removed or _skipped:
            logger.info("finalize: plan removals — removed=%s skipped=%s",
                        _removed, [x["node_id"] for x in _skipped])
            removal_events.append(_event("nodes_removed", {
                "removed": _removed, "skipped": _skipped,
            }))

    # 2026-06-18 (ENABLE_ORPHAN_RESOLVE): before the structural check, give the
    # agent one round to connect-or-remove any fully-disconnected orphan node,
    # instead of failing the whole build on a stray leftover (spc-ooc). No-op
    # unless the flag is on and an isolated node exists.
    from python_ai_sidecar.agent_builder.graph_build.nodes.orphan_resolve import (
        maybe_resolve_orphans,
    )
    _orphan_upd = await maybe_resolve_orphans(state)
    if _orphan_upd.get("final_pipeline"):
        final_dict = _orphan_upd["final_pipeline"]

    pipeline = PipelineJSON.model_validate(final_dict)
    registry = SeedlessBlockRegistry()
    registry.load()
    # Run the same validator the canvas Save flow uses. Most issues are
    # ADVISORY warnings (param-enum complaints, etc.) — the Glass Box
    # contract is that the returned pipeline is a draft and user explicitly
    # clicks Save to persist.
    #
    # 2026-05-10 EXCEPTION: structural errors (C14 orphan, C15 source-less,
    # C6 missing required param) are treated as BUILD-BLOCKING. They produce
    # pipelines that crash React Flow on canvas (white-screen) or fail at
    # runtime, and silently letting them through past finalize is what gave
    # the user the blank-canvas symptom. With these flagged as failed, the
    # frontend can show an error card instead of trying to render a broken
    # graph.
    validator = PipelineValidator(registry.catalog)
    issues = validator.validate(pipeline)

    # v24 D2: full-pipeline placeholder gate — catches `{xxx}` / `<xxx>` /
    # `:xxx` / runtime-concept literals that any LLM rewrite path (compile_chunk,
    # reflect_plan, repair_op) leaked into final_pipeline params. Caught here
    # so it routes through reflect_plan again with the v24-upgraded prompt.
    from python_ai_sidecar.agent_builder.graph_build.nodes.compile_chunk import (
        check_final_pipeline_placeholders,
    )
    _observed: set[str] = set()
    for snap in (state.get("exec_trace") or {}).values():
        if not isinstance(snap, dict): continue
        sample = snap.get("sample")
        if isinstance(sample, dict):
            for sv in sample.values():
                if isinstance(sv, str): _observed.add(sv)
                elif isinstance(sv, list):
                    for item in sv:
                        if isinstance(item, dict):
                            for x in item.values():
                                if isinstance(x, str): _observed.add(x)
    placeholder_issues = check_final_pipeline_placeholders(
        final_dict, state.get("instruction") or "", _observed,
        catalog=registry.catalog,
    )
    if placeholder_issues:
        logger.warning(
            "finalize_node: D2 placeholder gate caught %d leak(s): %s",
            len(placeholder_issues),
            "; ".join(p.get("message", "")[:120] for p in placeholder_issues[:3]),
        )
        issues = list(issues) + placeholder_issues

    # 2026-05-13: C4_PORT_COMPAT is now structural. Saw pipeline #135 ship
    # with edge n6→n3 (data_view → process_history) — process_history has
    # no `data` input port so the edge is meaningless, but the executor
    # treats target as a downstream-dependent node and skips it, cascading
    # the whole branch. Force the build to fail so reflect_plan repairs it.
    _STRUCTURAL_RULES = {
        "C6_PARAM_SCHEMA",
        "C14_ORPHAN_NODE",
        "C15_SOURCE_LESS_NODE",
        "C4_PORT_COMPAT",
        "C16_PLACEHOLDER_LEAK",  # v24 D2 — must trigger reflect_plan repair
    }
    structural_issues = [i for i in issues if i.get("rule") in _STRUCTURAL_RULES]
    advisory_issues = [i for i in issues if i.get("rule") not in _STRUCTURAL_RULES]

    n_ok_ops = sum(1 for op in plan if op.get("result_status") == "ok")
    n_failed_ops = sum(1 for op in plan if op.get("result_status") == "error")

    # v18: preserve "refused" status set by macro_plan/clarify_intent when
    # they hard-rejected. Without this, refused → finalize → "failed"
    # (because pipeline is empty), losing the distinction between "agent
    # tried + couldn't" and "agent refused to guess".
    incoming_status = state.get("status")
    # v30.17l hotfix: detect v30 ReAct path. v30 uses agentic_phase_loop
    # tool calls (add_node/connect/etc.) which update the pipeline directly
    # and DON'T populate `plan[i].result_status`. So n_ok_ops==0 always
    # for v30, but build succeeded if all phases advanced.
    v30_phases = state.get("v30_phases") or []
    v30_idx = state.get("v30_current_phase_idx", 0)
    is_v30_path = bool(v30_phases)
    v30_all_phases_done = is_v30_path and v30_idx >= len(v30_phases)

    if incoming_status == "refused":
        status = "refused"
    elif is_v30_path:
        # v30 path: phase completion is source of truth
        if len(pipeline.nodes) == 0:
            status = "failed"
        elif structural_issues:
            status = "failed_structural"
        elif v30_all_phases_done:
            status = "finished"
        elif v30_idx > 0:
            # some phases done but not all — partial success
            status = "build_partial"
        else:
            status = "failed"
    elif len(pipeline.nodes) == 0 or n_ok_ops == 0:
        # v27 path: count plan ops (legacy macro_plan / dispatch_op flow)
        status = "failed"
    elif structural_issues:
        status = "failed_structural"
    else:
        status = "finished"

    # C2: strict plan-deliverable check (ENABLE_STRICT_PHASE_OUTPUT, default OFF).
    # The phase loop's covers gate is advisory — a phase can advance WITHOUT its
    # expected terminal block on canvas — so v30 can mark all phases done yet ship
    # a pipeline missing the actual deliverable (user asked for a chart, pipeline
    # ends in block_filter). That silently became `finished` (ok=True) and the
    # false-success was invisible. Here we fact-check the plan's FINAL phase
    # deliverable kind against the built canvas's terminal blocks. This is a
    # plan-level deterministic fact check, NOT a prompt rule.
    missing_output_reason = ""
    if status == "finished" and is_v30_path and is_strict_phase_output_enabled():
        missing_output_reason = _missing_deliverable_reason(
            pipeline, v30_phases, registry
        )
        if missing_output_reason:
            status = "failed_missing_output"
            logger.warning(
                "finalize_node: strict_phase_output FAIL — %s", missing_output_reason
            )

    if status == "failed_missing_output":
        issue_summary = f" [no] missing deliverable — {missing_output_reason}"
    elif structural_issues:
        issue_summary = (
            f" ❌ {len(structural_issues)} structural error(s) — "
            f"pipeline cannot be safely rendered. Try the build again "
            f"(the agent will read the same descriptions and usually fixes "
            f"it on the second attempt)."
        )
    elif advisory_issues:
        issue_summary = (
            f" ⚠ {len(advisory_issues)} validator warning(s) — review on canvas"
        )
    else:
        issue_summary = ""
    summary = (
        f"Built {len(pipeline.nodes)} node(s), {len(pipeline.edges)} edge(s); "
        f"plan ops ok={n_ok_ops} failed={n_failed_ops}{issue_summary}"
    )
    logger.info("finalize_node: status=%s | %s", status, summary)

    # F5 (2026-07-10): give the built canvas a human name (LLM-suggested,
    # user-editable later). Skipped for empty/refused builds.
    if pipeline.nodes and status in ("finished", "build_partial", "failed_structural"):
        await _maybe_generate_pipeline_name(
            pipeline, str(state.get("instruction") or "")
        )
    if structural_issues:
        for si in structural_issues[:5]:
            logger.warning(
                "finalize_node: structural issue: rule=%s node=%s msg=%s",
                si.get("rule"), si.get("node_id") or si.get("node"),
                str(si.get("message"))[:200],
            )

    # Phase 10-C Fix 4 — best-effort runtime dry-run.
    # v31.2: removal events lead so the UI narrates 移除 before 完成.
    sse_events = removal_events + [_event("build_finalized", {
        "ok": status == "finished",
        "node_count": len(pipeline.nodes),
        "edge_count": len(pipeline.edges),
        "validator_warnings": len(advisory_issues),
        "validator_issues": advisory_issues[:5],  # cap to keep SSE small
        "structural_errors": structural_issues[:5],
        "missing_output_reason": missing_output_reason or None,
        "summary": summary,
    })]

    # v18 Tier 1.3 + 1.4: get tracer once, used for exec_trace + validation
    # snapshots in addition to dry_run.
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer,
    )
    tracer = get_current_tracer()

    # Tier 1.3: snapshot state.exec_trace into trace JSON so admin viewer
    # can audit "LLM picked col X but upstream actually had cols Y/Z" —
    # this evidence already exists in state but never written to disk.
    exec_trace = state.get("exec_trace") or {}
    if tracer is not None and exec_trace:
        # Cap each node's sample to keep trace JSON size manageable.
        compact_exec = {
            nid: {
                "block_id": snap.get("block_id"),
                "rows": snap.get("rows"),
                "cols": (snap.get("cols") or [])[:30],
                "sample": snap.get("sample") if isinstance(snap.get("sample"), dict) else None,
                "error": snap.get("error"),
                "after_cursor": snap.get("after_cursor"),
            }
            for nid, snap in exec_trace.items()
            if isinstance(snap, dict)
        }
        tracer.record_step(
            "exec_trace_snapshot",
            n_nodes=len(compact_exec),
            snapshots=compact_exec,
        )

    # Tier 1.4: surface validation issues as their own graph_step so the
    # admin viewer can show them prominently (currently buried in the
    # build_finalized SSE event).
    if tracer is not None and (structural_issues or advisory_issues):
        tracer.record_step(
            "validation_summary",
            status="failed_structural" if structural_issues else "warnings_only",
            n_structural=len(structural_issues),
            n_advisory=len(advisory_issues),
            structural=[
                {"rule": i.get("rule"), "node": i.get("node_id") or i.get("node"),
                 "message": str(i.get("message"))[:300]}
                for i in structural_issues[:10]
            ],
            advisory=[
                {"rule": i.get("rule"), "node": i.get("node_id") or i.get("node"),
                 "message": str(i.get("message"))[:300]}
                for i in advisory_issues[:10]
            ],
        )

    dry_run_results: dict[str, Any] | None = None
    if status == "finished":
        # 2026-05-13: pass state.trigger_payload so dry-run uses the same
        # inputs production /run will use. Without this, executor falls
        # back to _CANONICAL_INPUT_FALLBACKS which often don't match the
        # actual trigger — letting runtime-only failures slip past inspect.
        trigger_payload = state.get("trigger_payload") or {}
        dryrun_event, dry_run_results = await _maybe_dry_run(pipeline, trigger_payload)
        if dryrun_event:
            sse_events.append(dryrun_event)
        # Persist dry-run summary into the BuildTracer trace so the admin
        # /admin/build-traces viewer shows actual runtime data alongside
        # the planning steps. Without this, the trace only had the
        # plan + LLM calls — user couldn't see what each node actually
        # produced.
        if tracer is not None and dry_run_results is not None:
            node_results = (dry_run_results or {}).get("node_results") or {}
            compact = {
                nid: _compact_node_result(info)
                for nid, info in node_results.items()
            }
            tracer.record_step(
                "dry_run",
                status=dry_run_results.get("status"),
                duration_ms=dry_run_results.get("duration_ms"),
                node_results=compact,
            )

    # 2026-05-13: structural_issues persisted to state so inspect_execution
    # can also self-correct broken-pipeline cases (most common failure mode
    # — orphan / source-less nodes), not just runtime semantic issues. The
    # issues already carry ErrorEnvelope shape after Phase D.
    return {
        "status": status,
        "summary": summary,
        "final_pipeline": pipeline.model_dump(by_alias=True),
        "sse_events": sse_events,
        "dry_run_results": dry_run_results,
        "structural_issues": structural_issues,
    }


async def _maybe_dry_run(
    pipeline: PipelineJSON,
    trigger_payload: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run the pipeline once via PipelineExecutor.

    Returns (sse_event, raw_result). raw_result is the full executor return
    value — preserved so the downstream `inspect_execution` graph node can
    scan node_results for semantic issues (single-point charts, error
    verdicts, etc.) without re-running the executor.

    Build status NEVER changes based on this — the canvas is already built;
    this is purely informational.

    Skipped (raw_result=None) when:
      - GRAPH_BUILD_DRYRUN env var is set to "false"/"0"/"off"
      - pipeline contains a side-effect block (block_alert etc.)
    """
    flag = (os.environ.get("GRAPH_BUILD_DRYRUN") or "true").strip().lower()
    if flag in {"false", "0", "off", "no"}:
        return None, None

    side_effect_nodes = [
        n.id for n in pipeline.nodes if n.block_id in SIDE_EFFECT_BLOCKS
    ]
    if side_effect_nodes:
        logger.info("dry-run: skipped — pipeline has side-effect nodes %s", side_effect_nodes)
        return _event("runtime_check_skipped", {
            "reason": "side_effect_blocks_present",
            "blocks": side_effect_nodes,
        }), None

    try:
        block_registry = BlockRegistry()
        await block_registry.load_from_db(None)  # Java-backed, no local db needed
    except Exception as ex:  # noqa: BLE001
        logger.warning("dry-run: BlockRegistry load failed: %s", ex)
        return _event("runtime_check_skipped", {
            "reason": "registry_unavailable",
            "error": str(ex)[:200],
        }), None

    executor = PipelineExecutor(block_registry)
    # Map common synonyms — harness/Java side often uses snake_case suffix
    # variants (step_id vs step, equipment_id vs tool_id) that the agent's
    # input declarations may or may not match. Pass BOTH forms so the
    # executor's _resolve_inputs picks whichever the pipeline declared.
    resolved_inputs = _expand_trigger_aliases(trigger_payload or {})
    try:
        result = await asyncio.wait_for(
            executor.execute(pipeline, inputs=resolved_inputs),
            timeout=DRYRUN_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("dry-run: timed out after %.1fs", DRYRUN_TIMEOUT_SEC)
        return _event("runtime_check_timeout", {
            "timeout_sec": DRYRUN_TIMEOUT_SEC,
        }), None
    except Exception as ex:  # noqa: BLE001
        logger.warning("dry-run: executor crashed: %s", ex)
        return _event("runtime_check_failed", {
            "reason": "executor_crashed",
            "error": f"{type(ex).__name__}: {str(ex)[:300]}",
        }), None

    overall = (result or {}).get("status")
    node_results = (result or {}).get("node_results") or {}
    failed = [
        {"node_id": nid, "error": (info.get("error") if isinstance(info, dict)
                                   else getattr(info, "error", None))}
        for nid, info in node_results.items()
        if (info.get("status") if isinstance(info, dict)
            else getattr(info, "status", None)) == "failed"
    ]

    if overall == "success":
        logger.info("dry-run: pipeline executed cleanly (%d nodes)", len(node_results))
        return _event("runtime_check_ok", {
            "node_count": len(node_results),
        }), result
    if not failed:
        # Status not 'success' but no per-node failure — empty data, no_data, etc.
        return _event("runtime_check_no_data", {
            "status": overall,
            "message": (result or {}).get("error_message") or "pipeline produced no data",
        }), result
    return _event("runtime_check_failed", {
        "reason": "node_error",
        "failed_count": len(failed),
        "failures": failed[:5],
    }), result


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}


# Common naming variants between trigger payloads (production /run) and what
# pipelines declare. Adding both forms is cheap; _resolve_inputs only consumes
# names that match a declared input, ignoring extras.
_TRIGGER_ALIASES: dict[str, str] = {
    "step_id": "step",            # harness sends step_id; some pipelines declare step
    "equipment_id": "tool_id",    # harness sends equipment_id; many declare tool_id
}


def _expand_trigger_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {}
    out = dict(payload)
    for src, dst in _TRIGGER_ALIASES.items():
        if src in out and dst not in out:
            out[dst] = out[src]
        if dst in out and src not in out:
            out[src] = out[dst]
    return out
