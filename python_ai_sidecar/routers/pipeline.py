"""Pipeline Executor endpoints — JSON, not SSE.

Phase 4 mock. Phase 5 will import ``fastapi_backend_service.app.services.pipeline_executor``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..auth import CallerContext, ServiceAuth

router = APIRouter(prefix="/internal/pipeline", tags=["pipeline"])


class ExecuteRequest(BaseModel):
    pipeline_id: int | None = None
    pipeline_json: dict | None = None
    inputs: dict[str, Any] | None = None


class ValidateRequest(BaseModel):
    pipeline_json: dict


@router.post("/execute")
async def execute(req: ExecuteRequest, caller: CallerContext = ServiceAuth) -> dict:
    return {
        "ok": True,
        "run_id": -1,
        "status": "mock_success",
        "caller_user_id": caller.user_id,
        "mock_output": {
            "node_results": {
                "n_1": {"status": "success", "rows": 42, "duration_ms": 12},
            },
            "summary": "Phase 4 mock — real executor wires in Phase 5",
            "echo": {
                "pipeline_id": req.pipeline_id,
                "has_snapshot": req.pipeline_json is not None,
                "inputs_count": len(req.inputs or {}),
            },
        },
    }


@router.post("/validate")
async def validate(req: ValidateRequest, caller: CallerContext = ServiceAuth) -> dict:
    nodes = (req.pipeline_json or {}).get("nodes") or []
    return {
        "ok": True,
        "status": "mock_valid",
        "node_count": len(nodes),
        "caller_user_id": caller.user_id,
    }
