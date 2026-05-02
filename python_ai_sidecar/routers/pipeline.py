"""Pipeline Executor endpoints.

Phase 5a: /execute goes live — fetches the pipeline from Java, pretends to
run it (minimal echo executor), and writes an execution_log row back via Java.
This proves the reverse-auth round-trip. Phase 5c swaps the echo for
``fastapi_backend_service.app.services.pipeline_executor``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..auth import CallerContext, ServiceAuth
from ..clients.java_client import JavaAPIClient, JavaAPIError
from ..executor.block_runtime import REGISTRY as BLOCK_REGISTRY
from ..executor.dag import execute_dag
from ..executor.real_executor import (
    SIDECAR_NATIVE_BLOCKS,
    all_blocks_native,
    execute_native,
)

log = logging.getLogger("python_ai_sidecar.pipeline")
router = APIRouter(prefix="/internal/pipeline", tags=["pipeline"])


class ExecuteRequest(BaseModel):
    pipeline_id: int | None = None
    pipeline_json: dict | None = None
    inputs: dict[str, Any] | None = None
    triggered_by: str = "user"


class ValidateRequest(BaseModel):
    pipeline_json: dict


class PreviewRequest(BaseModel):
    """Run pipeline up to (and including) `node_id` and return that node's
    preview rows. Does NOT persist a PipelineRun. Mirrors the old
    fastapi-backend's POST /api/v1/pipeline-builder/preview that the
    Builder's RUN PREVIEW button used before the Java cutover."""
    pipeline_json: dict
    node_id: str
    sample_size: int = 100
    inputs: dict[str, Any] | None = None


def _node_count(pipeline_json: dict | None) -> int:
    if not isinstance(pipeline_json, dict):
        return 0
    nodes = pipeline_json.get("nodes")
    return len(nodes) if isinstance(nodes, list) else 0


async def _resolve_pipeline(java: JavaAPIClient, req: ExecuteRequest) -> tuple[dict | None, dict | None]:
    """Return (pipeline_entity_from_java, effective_json_to_execute).

    Rules:
      - If pipeline_id given, fetch from Java (source of truth).
      - Else if pipeline_json given, use that (ad-hoc run, no persisted record).
      - Else return (None, None).
    """
    if req.pipeline_id is not None:
        try:
            entity = await java.get_pipeline(req.pipeline_id)
        except JavaAPIError as ex:
            if ex.status == 404:
                raise HTTPException(status_code=404, detail=f"pipeline {req.pipeline_id} not found in Java")
            raise
        # JavaAPIClient._request normalises response keys to snake_case, so
        # the field we get back is `pipeline_json` (not the Java-side
        # camelCase `pipelineJson`). Reading the camelCase key returned None
        # and made the executor see an empty {} → "pipeline_json failed
        # schema validation" 500 (caught 2026-04-28 during pipeline audit).
        raw = entity.get("pipeline_json") or entity.get("pipelineJson")
        effective = json.loads(raw) if isinstance(raw, str) and raw else raw
        return entity, effective if isinstance(effective, dict) else {}
    if req.pipeline_json is not None:
        return None, req.pipeline_json
    return None, None


@router.post("/execute")
async def execute(req: ExecuteRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Execute a pipeline.

    Decision tree:
      1. If all blocks are in SIDECAR_NATIVE_BLOCKS → Phase 8-B native
         executor (full pandas DAG, validator, RunCache, etc.)
      2. Else → legacy 6-block demo walker (kept as safety net + for the
         sub-set of tests that depend on it).

    The :8001 fallback proxy was retired in 2026-05-02 cleanup; native
    executor covers all 47 production blocks, and the legacy walker still
    catches test-only fake blocks like load_inline_rows.
    """
    java = JavaAPIClient.for_caller(caller)
    entity, effective = await _resolve_pipeline(java, req)

    # Phase 8-B fast path: everything in whitelist → native executor.
    if isinstance(effective, dict) and all_blocks_native(effective):
        started = time.monotonic()
        try:
            result = await execute_native(
                effective,
                inputs=req.inputs,
                run_id=req.pipeline_id,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            status = result.get("status") or "error"
            # Java Jackson uses SNAKE_CASE — send snake_case keys.
            persisted = await java.create_execution_log({
                "triggered_by": req.triggered_by or "user",
                "status": "success" if status == "success" else "error",
                "llm_readable_data": json.dumps({
                    "source": "python_ai_sidecar_native",
                    "pipeline_id": req.pipeline_id,
                    "status": status,
                    "node_results": result.get("node_results") or {},
                    "result_summary": result.get("result_summary"),
                    "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
                }, ensure_ascii=False, default=str),
                "duration_ms": duration_ms,
                "error_message": result.get("error_message"),
            })
            return {
                "ok": status == "success",
                "execution_log_id": persisted.get("id") if isinstance(persisted, dict) else None,
                "caller_user_id": caller.user_id,
                "pipeline": {
                    "id": entity.get("id") if entity else None,
                    "name": entity.get("name") if entity else None,
                    "resolved": entity is not None or effective is not None,
                },
                "status": status,
                "source": "native",
                "node_results": result.get("node_results") or {},
                "result_summary": result.get("result_summary"),
                "duration_ms": duration_ms,
            }
        except Exception as ex:  # noqa: BLE001
            log.exception("native executor failed")
            raise HTTPException(
                status_code=500,
                detail={"code": "native_executor_failed", "message": str(ex)[:300]},
            )

    # Safety net: legacy demo walker (used by /validate tests that pass
    # fake blocks like load_inline_rows). For non-native real-world blocks
    # this will fail and the caller sees an error — the :8001 fallback was
    # retired since native executor covers all production blocks.
    started = time.monotonic()
    try:
        walk = execute_dag(effective)
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "success" if walk.get("status") == "success" else "error"
        persisted = await java.create_execution_log({
            "triggered_by": req.triggered_by or "user",
            "status": status,
            "llm_readable_data": json.dumps({
                "source": "python_ai_sidecar_demo",
                "pipeline_id": req.pipeline_id,
                "node_results": walk.get("node_results") or {},
                "terminal_nodes": walk.get("terminal_nodes") or [],
                "preview": walk.get("preview") or [],
                "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
            }, ensure_ascii=False),
            "duration_ms": duration_ms,
            "error_message": walk.get("reason") if walk.get("status") == "validation_error" else None,
        })
        return {
            "ok": status == "success",
            "execution_log_id": persisted.get("id") if isinstance(persisted, dict) else None,
            "caller_user_id": caller.user_id,
            "pipeline": {
                "id": entity.get("id") if entity else None,
                "name": entity.get("name") if entity else None,
                "resolved": entity is not None or effective is not None,
            },
            "status": status,
            "source": "demo",
            "node_results": walk.get("node_results") or {},
            "preview": walk.get("preview") or [],
            "duration_ms": duration_ms,
        }
    except JavaAPIError as ex:
        log.exception("Java API failed during /execute")
        raise HTTPException(status_code=502, detail={
            "code": "java_api_error", "status": ex.status, "message": ex.message,
        })


@router.post("/validate")
async def validate(req: ValidateRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Dry-run the DAG walker: topo-sort + block lookup without any I/O.
    Surfaces unknown blocks, cycles, and orphan edges before Frontend
    commits the pipeline."""
    try:
        walk = execute_dag(req.pipeline_json)
    except Exception as ex:  # noqa: BLE001 — DAGError on cycle, malformed JSON etc.
        return {
            "ok": False,
            "status": "validation_error",
            "error": str(ex)[:300],
            "caller_user_id": caller.user_id,
        }
    node_results = walk.get("node_results") or {}
    errors = [
        {"node_id": nid, "error": r.get("error")}
        for nid, r in node_results.items() if r.get("status") == "error"
    ]
    return {
        "ok": walk.get("status") == "success",
        "status": walk.get("status"),
        "node_count": len(node_results),
        "errors": errors,
        "terminal_nodes": walk.get("terminal_nodes") or [],
        "caller_user_id": caller.user_id,
    }


@router.post("/preview")
async def preview(req: PreviewRequest, caller: CallerContext = ServiceAuth) -> dict:
    """Truncate pipeline to ancestors of {node_id}, run them, return the
    target node's rows. Used by Builder's RUN PREVIEW button so the user
    can inspect a node's output mid-design without saving the pipeline.

    Inputs default to each declared input's `example` value when caller
    didn't supply one — same behavior as the old fastapi-backend route
    so a fresh draft pipeline previews cleanly without manual binding."""
    pipeline_json = req.pipeline_json or {}
    nodes = pipeline_json.get("nodes") or []
    edges = pipeline_json.get("edges") or []
    node_ids = {n.get("id") for n in nodes if n.get("id")}
    target = req.node_id
    if target not in node_ids:
        raise HTTPException(status_code=404, detail=f"node '{target}' not in pipeline")

    # BFS upstream from target collecting ancestors (inclusive).
    ancestors = {target}
    frontier = {target}
    while frontier:
        next_frontier: set[str] = set()
        for e in edges:
            from_node = (e.get("from") or {}).get("node")
            to_node = (e.get("to") or {}).get("node")
            if to_node in frontier and from_node and from_node not in ancestors:
                ancestors.add(from_node)
                next_frontier.add(from_node)
        frontier = next_frontier

    truncated_dict = {
        **pipeline_json,
        "nodes": [n for n in nodes if n.get("id") in ancestors],
        "edges": [
            e for e in edges
            if (e.get("from") or {}).get("node") in ancestors
               and (e.get("to") or {}).get("node") in ancestors
        ],
    }

    # Pydantic-parse the truncated subgraph; if it fails we surface the
    # exception text rather than 500-ing.
    from python_ai_sidecar.pipeline_builder.executor import PipelineJSON
    try:
        pipeline = PipelineJSON.model_validate(truncated_dict)
    except Exception as ex:  # noqa: BLE001
        return {
            "status": "validation_error",
            "errors": [{"rule": "PARSE", "message": str(ex)[:400]}],
            "caller_user_id": caller.user_id,
        }

    # Default each declared input's value to its `example` if caller didn't
    # provide one — keeps the preview useful on a fresh draft.
    preview_inputs = dict(req.inputs or {})
    for decl in pipeline.inputs or []:
        name = getattr(decl, "name", None)
        if not name:
            continue
        if preview_inputs.get(name) is None:
            example = getattr(decl, "example", None)
            if example is not None:
                preview_inputs[name] = example

    from python_ai_sidecar.executor.real_executor import get_real_executor
    executor = get_real_executor()
    try:
        result = await executor.execute(
            pipeline,
            preview_sample_size=req.sample_size,
            inputs=preview_inputs,
        )
    except Exception as ex:  # noqa: BLE001
        log.exception("preview executor failed")
        return {
            "status": "error",
            "error_message": f"executor failed: {ex}"[:400],
            "caller_user_id": caller.user_id,
        }

    node_results = result.get("node_results") or {}
    target_result = node_results.get(target)
    return {
        "status": result.get("status", "success"),
        "target": target,
        "node_result": target_result,
        "all_node_results": node_results,
        "result_summary": result.get("result_summary"),
        "caller_user_id": caller.user_id,
    }
