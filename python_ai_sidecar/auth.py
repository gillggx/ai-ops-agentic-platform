"""Service-token guard — enforced on every /internal/* request.

The Java API is the only legitimate caller. We check both:
  1. `X-Service-Token` header matches `SERVICE_TOKEN` env
  2. (Optional) caller IP is on the allow-list (supports plain IPs and CIDR
     ranges, e.g. ``172.16.0.0/12`` for Docker bridge networks). An empty
     allow-list short-circuits the check — token still gates the call.

The Java side injects `X-User-Id` + `X-User-Roles` headers so handlers that
care about who's asking can read them without doing their own auth.
"""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from .config import CONFIG

log = logging.getLogger(__name__)


def _compile_allow_list(entries: tuple[str, ...]) -> list[ipaddress._BaseNetwork]:
    """Convert each CSV entry into an ip_network. Bare IPs become /32 or /128.
    Invalid entries are skipped with a warning rather than killing startup."""
    networks: list[ipaddress._BaseNetwork] = []
    for raw in entries:
        try:
            networks.append(ipaddress.ip_network(raw, strict=False))
        except ValueError as exc:
            log.warning("ignoring malformed allowed-caller entry %r: %s", raw, exc)
    return networks


_ALLOWED_NETWORKS = _compile_allow_list(CONFIG.allowed_caller_ips)


def _ip_allowed(client_ip: str) -> bool:
    if not _ALLOWED_NETWORKS:
        return True
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in net for net in _ALLOWED_NETWORKS)


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
    # Empty / unset list = allow-all (token still gates the call).
    if _ALLOWED_NETWORKS:
        client_ip = request.client.host if request.client else ""
        if client_ip and not _ip_allowed(client_ip):
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
