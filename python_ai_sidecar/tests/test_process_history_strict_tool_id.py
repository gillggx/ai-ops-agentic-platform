"""Tests for ENABLE_STRICT_TOOL_ID gate in block_process_history.

Covers the case-insensitive 'ALL' / '*' rejection. When the flag is off
(default), legacy behaviour stands — the simulator route accepts 'ALL' as
a wildcard sentinel.
"""

from __future__ import annotations

import importlib

import pytest

from python_ai_sidecar.pipeline_builder.blocks.base import (
    BlockExecutionError,
    ExecutionContext,
)
from python_ai_sidecar.pipeline_builder.blocks.process_history import (
    ProcessHistoryBlockExecutor,
)


CTX = ExecutionContext()


def _reload(monkeypatch, *, strict: str):
    monkeypatch.setenv("ENABLE_STRICT_TOOL_ID", strict)
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)


@pytest.mark.asyncio
async def test_strict_off_allows_ALL_sentinel(monkeypatch):
    _reload(monkeypatch, strict="0")
    block = ProcessHistoryBlockExecutor()
    # We expect this to NOT raise INVALID_PARAM for the 'ALL' value alone.
    # It WILL raise for unreachable simulator, but we accept that — what we
    # care about is the strict check not firing.
    try:
        await block.execute(
            params={"tool_id": "ALL", "time_range": "1h"},
            inputs={}, context=CTX,
        )
    except BlockExecutionError as e:
        assert e.code != "INVALID_PARAM" or "strict mode" not in e.message


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["ALL", "all", "All", "*"])
async def test_strict_on_rejects_sentinel(monkeypatch, value):
    _reload(monkeypatch, strict="1")
    block = ProcessHistoryBlockExecutor()
    with pytest.raises(BlockExecutionError) as ei:
        await block.execute(
            params={"tool_id": value, "time_range": "1h"},
            inputs={}, context=CTX,
        )
    assert ei.value.code == "INVALID_PARAM"
    assert "strict mode" in ei.value.message
    assert "get_process_summary" in (ei.value.hint or "")


@pytest.mark.asyncio
async def test_strict_on_allows_real_tool_id(monkeypatch):
    """Strict mode must not block legitimate values like 'EQP-01'."""
    _reload(monkeypatch, strict="1")
    block = ProcessHistoryBlockExecutor()
    # Will fail downstream (simulator unreachable) but NOT with strict-mode error.
    try:
        await block.execute(
            params={"tool_id": "EQP-01", "time_range": "1h"},
            inputs={}, context=CTX,
        )
    except BlockExecutionError as e:
        assert "strict mode" not in e.message


@pytest.mark.asyncio
async def test_strict_on_allows_none_tool_id_when_lot_id_provided(monkeypatch):
    """Strict only checks tool_id; the three-of-three rule still applies."""
    _reload(monkeypatch, strict="1")
    block = ProcessHistoryBlockExecutor()
    # tool_id absent, lot_id provided — strict check should not fire.
    try:
        await block.execute(
            params={"lot_id": "LOT-001", "time_range": "1h"},
            inputs={}, context=CTX,
        )
    except BlockExecutionError as e:
        assert "strict mode" not in e.message
