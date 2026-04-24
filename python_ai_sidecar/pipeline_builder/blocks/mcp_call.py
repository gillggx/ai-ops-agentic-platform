"""block_mcp_call — generic MCP dispatcher.

Given an MCP name (from mcp_definitions table), this block:
  1. looks up the MCP's endpoint + method from api_config
  2. passes `args` (dict) as query params (GET) or JSON body (POST)
  3. turns the response into a DataFrame

Use case: avoid creating a bespoke block for every MCP. For MCPs that already
have a specialized block (e.g. `block_process_history` wrapping get_process_info),
prefer the specialized one — it understands response quirks like SPC flatten.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pandas as pd

from python_ai_sidecar.pipeline_builder._sidecar_deps import _get_session_factory
from python_ai_sidecar.pipeline_builder._sidecar_deps import MCPDefinitionRepository
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
    # Common wrappers: { events: [] }, { dataset: [] }, { items: [] }, { data: [] }
    for key in ("events", "dataset", "items", "data", "records", "rows"):
        val = resp_json.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    # Bare dict with scalar fields → single-row DF
    return [resp_json]


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

        # Look up MCP definition from DB
        factory = _get_session_factory()
        async with factory() as db:
            repo = MCPDefinitionRepository(db)
            mcp = await repo.get_by_name(mcp_name)
            if mcp is None:
                raise BlockExecutionError(
                    code="MCP_NOT_FOUND", message=f"MCP '{mcp_name}' not registered"
                )
            api_config_raw = getattr(mcp, "api_config", None) or "{}"

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

        # Dispatch
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
