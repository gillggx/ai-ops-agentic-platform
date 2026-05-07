"""block_list_objects — typed list-object dispatcher (sidecar-native).

Wraps the 5 list-type system MCPs behind a single block with a `kind` enum:
  tool → list_tools
  lot  → list_lots
  step → list_steps
  apc  → list_apcs
  spc  → list_spcs

Improves discoverability over the generic block_mcp_call escape hatch — the
agent / user sees "block_list_objects(kind='tool')" instead of having to
remember the MCP name. Underlying HTTP call delegates to the same path as
McpCallBlockExecutor.
"""

from __future__ import annotations

from typing import Any

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    BlockExecutor,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.mcp_call import McpCallBlockExecutor

KIND_TO_MCP: dict[str, str] = {
    "tool": "list_tools",
    "lot": "list_lots",
    "step": "list_steps",
    "apc": "list_apcs",
    "spc": "list_spcs",
}


class ListObjectsBlockExecutor(BlockExecutor):
    block_id = "block_list_objects"

    def __init__(self) -> None:
        super().__init__()
        self._mcp = McpCallBlockExecutor()

    async def execute(
        self,
        *,
        params: dict[str, Any],
        inputs: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        kind = self.require(params, "kind")
        if not isinstance(kind, str) or kind not in KIND_TO_MCP:
            raise BlockExecutionError(
                code="INVALID_PARAM",
                message=(
                    f"kind must be one of {sorted(KIND_TO_MCP)}; got {kind!r}"
                ),
            )
        args = params.get("args") or {}
        if not isinstance(args, dict):
            raise BlockExecutionError(
                code="INVALID_PARAM", message="args must be an object (dict)"
            )

        return await self._mcp.execute(
            params={"mcp_name": KIND_TO_MCP[kind], "args": args},
            inputs=inputs,
            context=context,
        )
