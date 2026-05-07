"""Unit tests for block_list_objects.

Verifies the kind→MCP dispatch contract. The underlying MCP HTTP path is
McpCallBlockExecutor's responsibility (already covered by the dispatcher
itself); here we only check that ListObjectsBlockExecutor:
  1. Translates the 5 valid kinds to the right MCP names
  2. Forwards args verbatim
  3. Rejects bad kind / bad args with INVALID_PARAM
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.list_objects import (
    KIND_TO_MCP,
    ListObjectsBlockExecutor,
)

CTX = ExecutionContext()


@pytest.mark.parametrize(
    "kind,expected_mcp",
    [
        ("tool", "list_tools"),
        ("lot", "list_active_lots"),
        ("step", "list_steps"),
        ("apc", "list_apcs"),
        ("spc", "list_spcs"),
    ],
)
@pytest.mark.asyncio
async def test_kind_dispatches_to_correct_mcp(kind: str, expected_mcp: str) -> None:
    """Each of the 5 kinds must map to its dedicated MCP name."""
    fake_df = pd.DataFrame([{"x": 1}])
    captured: dict[str, object] = {}

    async def fake_execute(*, params, inputs, context):  # type: ignore[no-untyped-def]
        captured["params"] = params
        return {"data": fake_df}

    block = ListObjectsBlockExecutor()
    with patch.object(block._mcp, "execute", side_effect=fake_execute):
        out = await block.execute(
            params={"kind": kind, "args": {"limit": 5}},
            inputs={},
            context=CTX,
        )

    assert captured["params"] == {"mcp_name": expected_mcp, "args": {"limit": 5}}
    assert out["data"] is fake_df


@pytest.mark.asyncio
async def test_args_default_to_empty_dict() -> None:
    """args is optional — None / missing should become {} when forwarded."""
    captured: dict[str, object] = {}

    async def fake_execute(*, params, inputs, context):  # type: ignore[no-untyped-def]
        captured["params"] = params
        return {"data": pd.DataFrame()}

    block = ListObjectsBlockExecutor()
    with patch.object(block._mcp, "execute", side_effect=fake_execute):
        await block.execute(params={"kind": "tool"}, inputs={}, context=CTX)

    assert captured["params"] == {"mcp_name": "list_tools", "args": {}}


@pytest.mark.asyncio
async def test_missing_kind_raises() -> None:
    block = ListObjectsBlockExecutor()
    with pytest.raises(BlockExecutionError) as ei:
        await block.execute(params={}, inputs={}, context=CTX)
    assert ei.value.code == "MISSING_PARAM"


@pytest.mark.asyncio
async def test_invalid_kind_raises() -> None:
    block = ListObjectsBlockExecutor()
    with pytest.raises(BlockExecutionError) as ei:
        await block.execute(
            params={"kind": "recipe"}, inputs={}, context=CTX
        )
    assert ei.value.code == "INVALID_PARAM"
    assert "kind must be one of" in ei.value.message


@pytest.mark.asyncio
async def test_args_must_be_dict() -> None:
    block = ListObjectsBlockExecutor()
    with pytest.raises(BlockExecutionError) as ei:
        await block.execute(
            params={"kind": "tool", "args": "limit=5"},
            inputs={},
            context=CTX,
        )
    assert ei.value.code == "INVALID_PARAM"


def test_kind_map_covers_5_known_list_mcps() -> None:
    """Guards against accidental kind drift / typo in MCP name."""
    assert KIND_TO_MCP == {
        "tool": "list_tools",
        "lot": "list_active_lots",
        "step": "list_steps",
        "apc": "list_apcs",
        "spc": "list_spcs",
    }
