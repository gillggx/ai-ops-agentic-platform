"""block_mcp_call — generic MCP dispatcher (sidecar-native).

Given an MCP name (from mcp_definitions), this block:
  1. Fetches MCP metadata via Java ``/internal/mcp-definitions``
     (sidecar doesn't own a DB — Java is the SSOT)
  2. Issues the MCP's HTTP call (GET query params / POST JSON body)
  3. Turns the response into a DataFrame

Phase 8-B change: the DB lookup was originally a direct SQLAlchemy call
(``MCPDefinitionRepository.get_by_name``). The sidecar now uses
``JavaAPIClient.get_mcp_by_name`` which lists + filters; that's fine at
current MCP catalog sizes (~20 rows).

Use case: avoid creating a bespoke block for every MCP. For MCPs that already
have a specialized block (e.g. ``block_process_history`` wrapping
get_process_info), prefer the specialized one — it understands response
quirks like SPC flatten.
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

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 30.0


def _flatten_response(resp_json: Any) -> list[dict[str, Any]]:
    """Normalize various MCP response shapes to a list-of-records."""
    if isinstance(resp_json, list):
        return [r for r in resp_json if isinstance(r, dict)]
    if not isinstance(resp_json, dict):
        return []
    for key in ("events", "dataset", "items", "data", "records", "rows"):
        val = resp_json.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return [resp_json]


def _make_java_client() -> JavaAPIClient:
    """Build a sidecar-native JavaAPIClient (no caller context — runs under
    the shared service token). Block executors are invoked deep in
    PipelineExecutor where the original request's CallerContext is not
    threaded through; that's acceptable for reads against
    ``/internal/mcp-definitions``.
    """
    return JavaAPIClient(
        base_url=CONFIG.java_api_url,
        token=CONFIG.java_internal_token,
        timeout_sec=CONFIG.java_timeout_sec,
    )


class McpCallBlockExecutor(BlockExecutor):
    block_id = "block_mcp_call"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        mcp_name: str = self.require(params, "mcp_name")
        args_raw = params.get("args") or {}
        if not isinstance(args_raw, dict):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="args must be an object (dict)"
            )

        # 1) Resolve MCP metadata via Java
        java = _make_java_client()
        try:
            mcp = await java.get_mcp_by_name(mcp_name)
        except JavaAPIError as e:
            raise BlockExecutionError(
                code="MCP_LOOKUP_FAILED",
                message=f"Java /internal/mcp-definitions lookup failed: {e.status} {e.message}",
            ) from None

        if mcp is None:
            raise BlockExecutionError(
                code="MCP_NOT_FOUND", message=f"MCP '{mcp_name}' not registered"
            )

        # Java DTO uses apiConfig (camelCase) — per Jackson SNAKE_CASE wire shape
        # comes through as api_config. Tolerate both.
        api_config_raw = mcp.get("api_config") or mcp.get("apiConfig") or "{}"
        try:
            api_config = json.loads(api_config_raw) if isinstance(api_config_raw, str) else api_config_raw
        except (TypeError, json.JSONDecodeError) as e:
            raise BlockExecutionError(
                code="INVALID_MCP_CONFIG",
                message=f"MCP '{mcp_name}' has malformed api_config: {e}",
            ) from None

        url = api_config.get("endpoint_url")
        method = (api_config.get("method") or "GET").upper()
        headers = api_config.get("headers") or {}
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

        # 2) Dispatch to the MCP's own endpoint
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                if method == "GET":
                    resp = await client.get(url, params=args_raw, headers=headers)
                else:
                    resp = await client.post(url, json=args_raw, headers=headers)
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
