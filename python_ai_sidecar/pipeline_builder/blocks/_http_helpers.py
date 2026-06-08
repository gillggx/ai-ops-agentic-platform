"""Shared HTTP helpers for MCP-call blocks.

Lifted out of ``block_mcp_call`` / ``block_mcp_proxy`` so the
``${ENV_VAR}`` interpolation rule stays in one place — both the
hand-written ``block_mcp_call`` and the V54 auto-generated proxy
blocks must behave identically when an MCP's api_config carries
secrets via ``headers``.

Design (POC skill-library branch, 2026-06-08):
- admin form stores headers as plain JSON in ``mcp_definitions.api_config``
- secret values use ``${NAME}`` placeholders, e.g.
  ``Authorization: "Bearer ${EXTERNAL_API_TOKEN}"``
- runtime resolves placeholders from the sidecar's process env so
  the DB row never holds the raw token
- unresolved placeholder → typed BlockExecutionError so user sees
  exactly which env var is missing rather than a generic 401
"""

from __future__ import annotations

import os
import re
from typing import Mapping

from python_ai_sidecar.pipeline_builder.blocks.base import BlockExecutionError

_PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def resolve_headers(
    headers: Mapping[str, object] | None, *, mcp_name: str,
) -> dict[str, str]:
    """Return a new dict with every ``${VAR}`` substring replaced by the
    sidecar's env var. Non-string values are coerced to str. Empty/None
    headers map → empty dict.

    Raises BlockExecutionError(INVALID_MCP_CONFIG) when a placeholder
    refers to an env var that isn't set, so user can fix .env without
    chasing a HTTP error from the upstream API.
    """
    if not headers:
        return {}
    resolved: dict[str, str] = {}
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        val = os.environ.get(name)
        if val is None:
            missing.append(name)
            return match.group(0)  # leave placeholder visible in error
        return val

    for key, raw in headers.items():
        value = str(raw)
        resolved[str(key)] = _PLACEHOLDER.sub(_sub, value)

    if missing:
        unique = ", ".join(sorted(set(missing)))
        raise BlockExecutionError(
            code="INVALID_MCP_CONFIG",
            message=(
                f"MCP '{mcp_name}' headers reference unset env var(s): {unique}"
            ),
            hint=(
                "Add them to python_ai_sidecar/.env (or the sidecar's systemd "
                "Environment lines) and restart aiops-python-sidecar."
            ),
        )
    return resolved
