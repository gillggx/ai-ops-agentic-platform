"""Liveness / readiness checks — token-gated to prevent anonymous probing."""

from __future__ import annotations

from fastapi import APIRouter

from ..auth import ServiceAuth, CallerContext

router = APIRouter(prefix="/internal/health", tags=["health"])


@router.get("")
async def health(caller: CallerContext = ServiceAuth) -> dict:
    return {
        "ok": True,
        "service": "python_ai_sidecar",
        "status": "UP",
        "caller_user_id": caller.user_id,
        "caller_roles": list(caller.roles),
    }
