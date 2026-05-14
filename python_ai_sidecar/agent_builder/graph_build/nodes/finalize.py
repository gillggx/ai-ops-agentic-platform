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


def _compact_node_result(info: dict[str, Any]) -> dict[str, Any]:
    """Trim a node_result for trace storage — drop full preview rows
    (can be huge), keep cols list + first row + per-port chart-type +
    n_data_points. Mirrors what the admin viewer needs.
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
                "columns": (blob.get("columns") or [])[:20],
                "total": blob.get("total"),
                "first_row": rows[0] if rows else None,
            }
        elif t == "dict":
            snap = blob.get("snapshot") or {}
            if isinstance(snap, dict) and "data" in snap:
                data = snap.get("data")
                ports[port] = {
                    "kind": "chart_spec",
                    "chart_type": snap.get("type"),
                    "title": snap.get("title"),
                    "n_data_points": len(data) if isinstance(data, list) else None,
                }
            else:
                ports[port] = {"kind": "dict", "keys": list(snap.keys())[:10]}
        elif t == "bool":
            ports[port] = {"kind": "bool", "value": blob.get("value")}
        else:
            ports[port] = {"kind": t}
    if ports:
        out["ports"] = ports
    return out


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
    }
    structural_issues = [i for i in issues if i.get("rule") in _STRUCTURAL_RULES]
    advisory_issues = [i for i in issues if i.get("rule") not in _STRUCTURAL_RULES]

    n_ok_ops = sum(1 for op in plan if op.get("result_status") == "ok")
    n_failed_ops = sum(1 for op in plan if op.get("result_status") == "error")

    # Status reflects the BUILD ENGINE's success, not pipeline validity —
    # but structural errors are loud enough to fail the build (see comment
    # above).
    if len(pipeline.nodes) == 0 or n_ok_ops == 0:
        status = "failed"
    elif structural_issues:
        status = "failed_structural"
    else:
        status = "finished"

    if structural_issues:
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
    if structural_issues:
        for si in structural_issues[:5]:
            logger.warning(
                "finalize_node: structural issue: rule=%s node=%s msg=%s",
                si.get("rule"), si.get("node_id") or si.get("node"),
                str(si.get("message"))[:200],
            )

    # Phase 10-C Fix 4 — best-effort runtime dry-run.
    sse_events = [_event("build_finalized", {
        "ok": status == "finished",
        "node_count": len(pipeline.nodes),
        "edge_count": len(pipeline.edges),
        "validator_warnings": len(advisory_issues),
        "validator_issues": advisory_issues[:5],  # cap to keep SSE small
        "structural_errors": structural_issues[:5],
        "summary": summary,
    })]

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
        from python_ai_sidecar.agent_builder.graph_build.trace import (
            get_current_tracer,
        )
        tracer = get_current_tracer()
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
