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
    # Run the same validator the canvas Save flow uses, but treat its issues
    # as ADVISORY warnings — not build failures. The Glass Box contract is
    # that the returned pipeline is a draft on canvas; user explicitly
    # clicks Save to persist (and that's where blocking validation happens).
    # Marking the build "failed" because of a param-enum complaint mismatched
    # the user's mental model — the canvas DID get nodes & edges.
    validator = PipelineValidator(registry.catalog)
    issues = validator.validate(pipeline)

    n_ok_ops = sum(1 for op in plan if op.get("result_status") == "ok")
    n_failed_ops = sum(1 for op in plan if op.get("result_status") == "error")

    # Status reflects the BUILD ENGINE's success, not pipeline validity.
    # Engine succeeded if any op completed and we have a non-empty canvas.
    if len(pipeline.nodes) == 0 or n_ok_ops == 0:
        status = "failed"
    else:
        status = "finished"

    issue_summary = (
        f" ⚠ {len(issues)} validator warning(s) — review on canvas before saving"
        if issues else ""
    )
    summary = (
        f"Built {len(pipeline.nodes)} node(s), {len(pipeline.edges)} edge(s); "
        f"plan ops ok={n_ok_ops} failed={n_failed_ops}{issue_summary}"
    )
    logger.info("finalize_node: status=%s | %s", status, summary)

    # Phase 10-C Fix 4 — best-effort runtime dry-run.
    sse_events = [_event("build_finalized", {
        "ok": status == "finished",
        "node_count": len(pipeline.nodes),
        "edge_count": len(pipeline.edges),
        "validator_warnings": len(issues),
        "validator_issues": issues[:5],  # cap to keep SSE small
        "summary": summary,
    })]

    if status == "finished":
        dryrun_event = await _maybe_dry_run(pipeline)
        if dryrun_event:
            sse_events.append(dryrun_event)

    return {
        "status": status,
        "summary": summary,
        "final_pipeline": pipeline.model_dump(by_alias=True),
        "sse_events": sse_events,
    }


async def _maybe_dry_run(pipeline: PipelineJSON) -> dict[str, Any] | None:
    """Run the pipeline once via PipelineExecutor, fire-and-forget the result
    as a `runtime_check_*` SSE event. Build status NEVER changes based on
    this — the canvas is already built; this is purely informational.

    Skipped when:
      - GRAPH_BUILD_DRYRUN env var is set to "false"/"0"/"off"
      - pipeline contains a side-effect block (block_alert etc.)
    """
    flag = (os.environ.get("GRAPH_BUILD_DRYRUN") or "true").strip().lower()
    if flag in {"false", "0", "off", "no"}:
        return None

    side_effect_nodes = [
        n.id for n in pipeline.nodes if n.block_id in SIDE_EFFECT_BLOCKS
    ]
    if side_effect_nodes:
        logger.info("dry-run: skipped — pipeline has side-effect nodes %s", side_effect_nodes)
        return _event("runtime_check_skipped", {
            "reason": "side_effect_blocks_present",
            "blocks": side_effect_nodes,
        })

    try:
        block_registry = BlockRegistry()
        await block_registry.load_from_db(None)  # Java-backed, no local db needed
    except Exception as ex:  # noqa: BLE001
        logger.warning("dry-run: BlockRegistry load failed: %s", ex)
        return _event("runtime_check_skipped", {
            "reason": "registry_unavailable",
            "error": str(ex)[:200],
        })

    executor = PipelineExecutor(block_registry)
    try:
        result = await asyncio.wait_for(
            executor.execute(pipeline, inputs={}),
            timeout=DRYRUN_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("dry-run: timed out after %.1fs", DRYRUN_TIMEOUT_SEC)
        return _event("runtime_check_timeout", {
            "timeout_sec": DRYRUN_TIMEOUT_SEC,
        })
    except Exception as ex:  # noqa: BLE001
        logger.warning("dry-run: executor crashed: %s", ex)
        return _event("runtime_check_failed", {
            "reason": "executor_crashed",
            "error": f"{type(ex).__name__}: {str(ex)[:300]}",
        })

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
        })
    if not failed:
        # Status not 'success' but no per-node failure — empty data, no_data, etc.
        return _event("runtime_check_no_data", {
            "status": overall,
            "message": (result or {}).get("error_message") or "pipeline produced no data",
        })
    return _event("runtime_check_failed", {
        "reason": "node_error",
        "failed_count": len(failed),
        "failures": failed[:5],
    })


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
