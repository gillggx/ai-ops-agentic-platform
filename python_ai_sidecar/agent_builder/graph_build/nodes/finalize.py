"""finalize_node — pure code: PipelineValidator + emit build_finalized SSE.

DB persistence is intentionally NOT done here. The Glass Box flow's
contract is: returned pipeline is a draft on the canvas; user's explicit
"Save" click is what writes to pb_pipelines (handled by frontend's normal
save-pipeline endpoint). v2 keeps that contract — finalize only validates
and packages the final state.
"""
from __future__ import annotations

import logging
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.pipeline_builder.pipeline_schema import PipelineJSON
from python_ai_sidecar.pipeline_builder.validator import PipelineValidator
from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry


logger = logging.getLogger(__name__)


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

    return {
        "status": status,
        "summary": summary,
        "final_pipeline": pipeline.model_dump(by_alias=True),
        "sse_events": [_event("build_finalized", {
            "ok": status == "finished",
            "node_count": len(pipeline.nodes),
            "edge_count": len(pipeline.edges),
            "validator_warnings": len(issues),
            "validator_issues": issues[:5],  # cap to keep SSE small
            "summary": summary,
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
