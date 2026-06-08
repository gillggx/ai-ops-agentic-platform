"""block_mcp_proxy — runtime executor for V54 auto-generated blocks.

When a System MCP is created with ``produces_block=true``, Java inserts a
pb_blocks row whose ``implementation`` JSON has ``type="mcp_proxy"`` and
``mcp_name="<the MCP>"``. This executor is the one the BlockRegistry hands
back for those blocks: it reads ``mcp_name`` from the block's spec (not
from runtime params) and dispatches via the same code path as
``block_mcp_call``.

Why a separate executor (vs. just using block_mcp_call):
  - User-facing param naming: block_mcp_call exposes a generic ``args``
    dict; the proxy executor lets the auto-generated block's own
    ``param_schema`` define friendly per-MCP params. We translate those
    into the ``args`` dict transparently.
  - Decoupling: changes to block_mcp_call's invocation surface (e.g.
    headers, timeout config) flow through here automatically because we
    delegate, not copy.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pandas as pd

from python_ai_sidecar.clients.java_client import JavaAPIClient, JavaAPIError
from python_ai_sidecar.config import CONFIG
from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.mcp_call import _flatten_response

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0


class McpProxyBlockExecutor(BlockExecutor):
    """Dispatcher for blocks where ``implementation.type == 'mcp_proxy'``.

    BlockRegistry assigns this executor when it sees the proxy marker on a
    block spec, so this class is never registered under a concrete block_id
    in BUILTIN_EXECUTORS. Instead, the registry instantiates one and binds
    it to the dynamic block name at load time.
    """

    block_id = "__mcp_proxy__"  # synthetic — not a real block name

    def __init__(self, mcp_name: str | None = None) -> None:
        super().__init__()
        # Spec-bound at registry load time. None means "look up from
        # implementation on every execute" (used by tests).
        self._bound_mcp_name = mcp_name

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        mcp_name = self._bound_mcp_name or params.get("_mcp_name")
        if not mcp_name:
            raise BlockExecutionError(
                code="MCP_PROXY_MISCONFIGURED",
                message="McpProxyBlockExecutor invoked without a bound MCP name",
                hint="block spec implementation.mcp_name must be set at registry load time",
            )

        java = JavaAPIClient(
            base_url=CONFIG.java_api_url,
            token=CONFIG.java_internal_token,
            timeout_sec=CONFIG.java_timeout_sec,
        )
        try:
            mcp = await java.get_mcp_by_name(mcp_name)
        except JavaAPIError as e:
            raise BlockExecutionError(
                code="MCP_LOOKUP_FAILED",
                message=f"Java /internal/mcp-definitions lookup failed: {e.status} {e.message}",
            ) from None
        if mcp is None:
            raise BlockExecutionError(
                code="MCP_NOT_FOUND",
                message=f"Source MCP '{mcp_name}' no longer registered",
                hint="The MCP may have been deleted while its derivative block remained.",
            )

        api_config = _read_api_config(mcp, mcp_name)
        url = api_config.get("endpoint_url")
        method = (api_config.get("method") or "GET").upper()
        from python_ai_sidecar.pipeline_builder.blocks._http_helpers import (
            resolve_headers,
        )
        headers = resolve_headers(api_config.get("headers"), mcp_name=mcp_name)
        if not url:
            raise BlockExecutionError(
                code="INVALID_MCP_CONFIG",
                message=f"MCP '{mcp_name}' has no endpoint_url",
            )
        if method not in {"GET", "POST"}:
            raise BlockExecutionError(
                code="INVALID_MCP_CONFIG",
                message=f"MCP '{mcp_name}' has unsupported method '{method}'",
            )

        # Auto-generated blocks expose the MCP input fields as their own
        # params (per param_schema). Pass all non-underscore keys through
        # to the MCP — the underscore prefix is reserved for executor-internal
        # plumbing (e.g. ``_mcp_name`` override above for tests).
        args = {k: v for k, v in params.items() if not k.startswith("_")}

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                if method == "GET":
                    resp = await client.get(url, params=args, headers=headers)
                else:
                    resp = await client.post(url, json=args, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPStatusError as e:
            raise BlockExecutionError(
                code="MCP_HTTP_ERROR",
                message=f"MCP '{mcp_name}' returned {e.response.status_code}: {e.response.text[:200]}",
            ) from None
        except httpx.RequestError as e:
            raise BlockExecutionError(
                code="MCP_UNREACHABLE",
                message=f"Failed to reach MCP '{mcp_name}' at {url}: {e}",
            ) from None

        records = _flatten_response(payload)
        return {"data": pd.DataFrame(records)}


def _read_api_config(mcp: dict[str, Any], mcp_name: str) -> dict[str, Any]:
    """Pull api_config dict from the Java MCP detail DTO. Tolerates either
    snake_case or camelCase since Phase 12 standardised on snake but historic
    rows may differ.
    """
    raw = mcp.get("api_config") or mcp.get("apiConfig") or "{}"
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError) as e:
        raise BlockExecutionError(
            code="INVALID_MCP_CONFIG",
            message=f"MCP '{mcp_name}' has malformed api_config: {e}",
        ) from None
