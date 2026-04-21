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
from ..fallback import python_proxy as fb

log = logging.getLogger("python_ai_sidecar.pipeline")
router = APIRouter(prefix="/internal/pipeline", tags=["pipeline"])


class ExecuteRequest(BaseModel):
    pipeline_id: int | None = None
    pipeline_json: dict | None = None
    inputs: dict[str, Any] | None = None
    triggered_by: str = "user"


class ValidateRequest(BaseModel):
    pipeline_json: dict


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
        raw = entity.get("pipelineJson")
        effective = json.loads(raw) if isinstance(raw, str) and raw else raw
        return entity, effective if isinstance(effective, dict) else {}
    if req.pipeline_json is not None:
        return None, req.pipeline_json
    return None, None


def _has_unknown_block(pipeline_json: dict | None) -> bool:
    if not isinstance(pipeline_json, dict):
        return False
    for n in pipeline_json.get("nodes") or []:
        block = n.get("block") or n.get("type")
        if block and block not in BLOCK_REGISTRY:
            return True
    return False


async def _fallback_execute(req: ExecuteRequest, caller: CallerContext) -> dict | None:
    """Proxy /execute to old Python's equivalent endpoint. Returns None if
    fallback disabled or upstream fails (caller falls back to native DAG)."""
    if not fb.fallback_enabled():
        return None
    try:
        body: dict = {}
        if req.pipeline_id is not None:
            body["pipeline_id"] = req.pipeline_id
        if req.pipeline_json is not None:
            body["pipeline_json"] = req.pipeline_json
        if req.inputs is not None:
            body["inputs"] = req.inputs
        body["triggered_by"] = req.triggered_by
        upstream = await fb.post_json("/api/v1/pipeline-builder/execute", body, caller)
        return {
            "ok": True,
            "caller_user_id": caller.user_id,
            "source": "python_fallback",
            "upstream": upstream,
        }
    except Exception as ex:  # noqa: BLE001 — try native executor instead
        log.warning("pipeline/execute fallback failed (%s) — using native DAG walker", ex.__class__.__name__)
        return None


@router.post("/execute")
async def execute(req: ExecuteRequest, caller: CallerContext = ServiceAuth) -> dict:
    java = JavaAPIClient.for_caller(caller)
    entity, effective = await _resolve_pipeline(java, req)

    # Phase 7 hybrid: if the pipeline uses blocks we haven't ported, delegate
    # to old Python which still has the full block registry.
    if _has_unknown_block(effective):
        fallback = await _fallback_execute(req, caller)
        if fallback is not None:
            return fallback

    started = time.monotonic()
    try:
        # Phase 5c: run the real DAG walker. Unknown block names surface as
        # node-level errors (not an exception) so partial results still persist.
        walk = execute_dag(effective)
        duration_ms = int((time.monotonic() - started) * 1000)
        status = "success" if walk.get("status") == "success" else "error"
        persisted = await java.create_execution_log({
            "triggeredBy": req.triggered_by or "user",
            "status": status,
            "llmReadableData": json.dumps({
                "source": "python_ai_sidecar",
                "pipeline_id": req.pipeline_id,
                "node_results": walk.get("node_results") or {},
                "terminal_nodes": walk.get("terminal_nodes") or [],
                "preview": walk.get("preview") or [],
                "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
            }, ensure_ascii=False),
            "durationMs": duration_ms,
            "errorMessage": walk.get("reason") if walk.get("status") == "validation_error" else None,
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
