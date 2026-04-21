"""Service-token guard — enforced on every /internal/* request.

The Java API is the only legitimate caller. We check both:
  1. `X-Service-Token` header matches `SERVICE_TOKEN` env
  2. (Optional) caller IP is on the allow-list

The Java side injects `X-User-Id` + `X-User-Roles` headers so handlers that
care about who's asking can read them without doing their own auth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from .config import CONFIG


@dataclass(frozen=True)
class CallerContext:
    user_id: Optional[int]
    roles: tuple[str, ...]


async def require_service_token(
    request: Request,
    x_service_token: str = Header(default="", alias="X-Service-Token"),
    x_user_id: str = Header(default="", alias="X-User-Id"),
    x_user_roles: str = Header(default="", alias="X-User-Roles"),
) -> CallerContext:
    if x_service_token != CONFIG.service_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid service token",
        )

    # Optional IP allow-list — defence in depth against misrouted traffic.
    if CONFIG.allowed_caller_ips:
        client_ip = request.client.host if request.client else ""
        if client_ip and client_ip not in CONFIG.allowed_caller_ips:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"caller ip {client_ip} not allowed",
            )

    parsed_uid: Optional[int] = None
    if x_user_id.strip():
        try:
            parsed_uid = int(x_user_id.strip())
        except ValueError:
            parsed_uid = None

    roles = tuple(r.strip() for r in x_user_roles.split(",") if r.strip())
    return CallerContext(user_id=parsed_uid, roles=roles)


ServiceAuth = Depends(require_service_token)
