"""Python sandbox runner.

Phase 4 mock — echoes the code. Phase 5 will wire
``fastapi_backend_service.app.services.sandbox_service``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..auth import CallerContext, ServiceAuth

router = APIRouter(prefix="/internal/sandbox", tags=["sandbox"])


class SandboxRequest(BaseModel):
    code: str = Field(..., min_length=1)
    inputs: dict | None = None
    timeout_sec: int = 10


@router.post("/run")
async def run(req: SandboxRequest, caller: CallerContext = ServiceAuth) -> dict:
    return {
        "ok": True,
        "status": "mock_ok",
        "caller_user_id": caller.user_id,
        "stdout": "",
        "stderr": "",
        "result": {
            "code_chars": len(req.code),
            "input_keys": list((req.inputs or {}).keys()),
            "timeout_sec": req.timeout_sec,
            "note": "Phase 4 mock — real sandbox wires in Phase 5",
        },
    }
