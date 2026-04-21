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


@router.post("/execute")
async def execute(req: ExecuteRequest, caller: CallerContext = ServiceAuth) -> dict:
    java = JavaAPIClient.for_caller(caller)
    entity, effective = await _resolve_pipeline(java, req)

    started = time.monotonic()
    try:
        node_count = _node_count(effective)
        # Phase 5a minimal "executor": record inputs echo + node count.
        # Phase 5c swaps this for pipeline_executor.py imported from
        # fastapi_backend_service.
        node_results = {
            f"n_{i}": {"status": "success", "rows": 1, "duration_ms": 1}
            for i in range(max(node_count, 1))
        }
        duration_ms = int((time.monotonic() - started) * 1000)
        persisted = await java.create_execution_log({
            "triggeredBy": req.triggered_by or "user",
            "status": "success",
            "llmReadableData": json.dumps({
                "source": "python_ai_sidecar",
                "node_count": node_count,
                "node_results": node_results,
                "inputs_echo": {k: str(v)[:100] for k, v in (req.inputs or {}).items()},
                "pipeline_id": req.pipeline_id,
            }),
            "durationMs": duration_ms,
        })
        return {
            "ok": True,
            "execution_log_id": persisted.get("id") if isinstance(persisted, dict) else None,
            "caller_user_id": caller.user_id,
            "pipeline": {
                "id": entity.get("id") if entity else None,
                "name": entity.get("name") if entity else None,
                "resolved": entity is not None or effective is not None,
            },
            "node_results": node_results,
            "duration_ms": duration_ms,
        }
    except JavaAPIError as ex:
        log.exception("Java API failed during /execute")
        raise HTTPException(status_code=502, detail={
            "code": "java_api_error", "status": ex.status, "message": ex.message,
        })


@router.post("/validate")
async def validate(req: ValidateRequest, caller: CallerContext = ServiceAuth) -> dict:
    nodes = (req.pipeline_json or {}).get("nodes") or []
    return {
        "ok": True,
        "status": "mock_valid",
        "node_count": len(nodes),
        "caller_user_id": caller.user_id,
    }
