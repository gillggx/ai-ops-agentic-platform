"""block_mcp_foreach — call an MCP once per upstream row, merge responses as columns.

Use case: Skill 5 pattern "for each process in history, fetch APC context".
Previously required custom Python; now:
  process_history → mcp_foreach(mcp_name='get_process_context',
                                 args_template={'targetID': '$lotID', 'step': '$step'},
                                 result_prefix='apc_') → downstream

Result merging:
  - If MCP returns a flat dict → each key becomes a new column (optionally prefixed)
  - If MCP returns a list of dicts → first item is merged (for 1:1 expansion)
  - Other shapes → stored as JSON string in `<prefix>raw`

Errors: any single call raising stops the whole block (fail-fast, deterministic).
Concurrency: asyncio.Semaphore(max_concurrency) caps parallel in-flight requests.
"""

from __future__ import annotations

import asyncio
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
_DEFAULT_MAX_CONCURRENCY = 5
_MAX_ROWS = 500  # safety cap — mcp_foreach on huge DFs would DoS the target


def _resolve_args(template: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Replace `"$col"` values in template with row[col]."""
    out: dict[str, Any] = {}
    for k, v in template.items():
        if isinstance(v, str) and v.startswith("$"):
            col = v[1:]
            if col not in row:
                raise BlockExecutionError(
                    code="COLUMN_NOT_FOUND",
                    message=f"args_template references ${col} but row has no '{col}'",
                )
            out[k] = row[col]
        else:
            out[k] = v
    return out


def _flatten_response(resp: Any, prefix: str) -> dict[str, Any]:
    """Turn an MCP response into {col: val} dict for merging into the row."""
    if isinstance(resp, dict):
        return {f"{prefix}{k}": v for k, v in resp.items()}
    if isinstance(resp, list) and resp:
        first = resp[0]
        if isinstance(first, dict):
            return {f"{prefix}{k}": v for k, v in first.items()}
    # Scalar / unrecognized → stash as JSON string
    return {f"{prefix}raw": json.dumps(resp, ensure_ascii=False, default=str)}


class McpForeachBlockExecutor(BlockExecutor):
    block_id = "block_mcp_foreach"

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        df = inputs.get("data")
        if not isinstance(df, pd.DataFrame):
            raise BlockExecutionError(
                code="INVALID_INPUT", message="'data' must be DataFrame"
            )
        if len(df) > _MAX_ROWS:
            raise BlockExecutionError(
                code="TOO_MANY_ROWS",
                message=f"mcp_foreach capped at {_MAX_ROWS} rows (upstream has {len(df)}). "
                f"Filter / limit upstream first.",
            )

        mcp_name: str = self.require(params, "mcp_name")
        args_template = self.require(params, "args_template")
        if not isinstance(args_template, dict):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="args_template must be an object"
            )
        result_prefix: str = params.get("result_prefix") or ""
        try:
            max_concurrency = int(params.get("max_concurrency", _DEFAULT_MAX_CONCURRENCY))
        except (TypeError, ValueError):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="max_concurrency must be integer"
            ) from None
        if max_concurrency < 1:
            max_concurrency = 1

        # Resolve MCP config once
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
                code="INVALID_MCP_CONFIG", message=f"MCP '{mcp_name}' has no endpoint_url"
            )
        if method not in {"GET", "POST"}:
            raise BlockExecutionError(
                code="INVALID_MCP_CONFIG",
                message=f"MCP '{mcp_name}' has unsupported method '{method}'",
            )

        rows = df.to_dict(orient="records")
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _call_one(client: httpx.AsyncClient, row: dict[str, Any]) -> dict[str, Any]:
            args = _resolve_args(args_template, row)
            async with semaphore:
                try:
                    if method == "GET":
                        resp = await client.get(url, params=args, headers=headers)
                    else:
                        resp = await client.post(url, json=args, headers=headers)
                    resp.raise_for_status()
                    return resp.json()
                except httpx.HTTPStatusError as e:
                    raise BlockExecutionError(
                        code="MCP_HTTP_ERROR",
                        message=f"MCP '{mcp_name}' row={row} returned {e.response.status_code}",
                    ) from None
                except httpx.RequestError as e:
                    raise BlockExecutionError(
                        code="MCP_UNREACHABLE",
                        message=f"MCP '{mcp_name}' unreachable: {e}",
                    ) from None

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            coros = [_call_one(client, row) for row in rows]
            # gather raises the first BlockExecutionError; asyncio will cancel the rest
            responses = await asyncio.gather(*coros)

        # Merge responses back as new columns per row
        merged_rows: list[dict[str, Any]] = []
        for row, resp in zip(rows, responses):
            extra = _flatten_response(resp, result_prefix)
            merged_rows.append({**row, **extra})
        return {"data": pd.DataFrame(merged_rows)}
