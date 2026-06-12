"""Tests for shared agent_knowledge injection (build_knowledge_hint) + the
ENABLE_PLAN_KNOWLEDGE gate on goal_plan_node."""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock, patch

import pytest

from python_ai_sidecar.agent_builder.graph_build.nodes._knowledge_inject import (
    build_knowledge_hint,
)


@pytest.mark.asyncio
async def test_build_knowledge_hint_layer1_high_priority():
    """High-priority rows render under 'Domain first principles'."""
    fake_java = AsyncMock()
    fake_java.list_high_priority_knowledge.return_value = [
        {"title": "參數分佈 chart 用 flat-mode 別 unnest",
         "body": "用 nested=false 或 block_select，不要 block_unnest 巢狀 dict"},
    ]
    with patch(
        "python_ai_sidecar.clients.java_client.JavaAPIClient",
        return_value=fake_java,
    ), patch(
        "python_ai_sidecar.agent_orchestrator_v2.nodes.load_context._build_knowledge_block",
        new=AsyncMock(return_value=""),
    ):
        out = await build_knowledge_hint("box plot by recipe", user_id=1)
    assert "Domain first principles" in out
    assert "參數分佈 chart 用 flat-mode 別 unnest" in out
    assert "block_select" in out


@pytest.mark.asyncio
async def test_build_knowledge_hint_layer2_rag():
    """RAG block is appended after the high-priority section."""
    fake_java = AsyncMock()
    fake_java.list_high_priority_knowledge.return_value = []
    with patch(
        "python_ai_sidecar.clients.java_client.JavaAPIClient",
        return_value=fake_java,
    ), patch(
        "python_ai_sidecar.agent_orchestrator_v2.nodes.load_context._build_knowledge_block",
        new=AsyncMock(return_value="## RAG-matched\n  recipe grouping hint"),
    ):
        out = await build_knowledge_hint("box plot by recipe", user_id=1)
    assert "RAG-matched" in out


@pytest.mark.asyncio
async def test_build_knowledge_hint_empty_when_nothing():
    fake_java = AsyncMock()
    fake_java.list_high_priority_knowledge.return_value = []
    with patch(
        "python_ai_sidecar.clients.java_client.JavaAPIClient",
        return_value=fake_java,
    ), patch(
        "python_ai_sidecar.agent_orchestrator_v2.nodes.load_context._build_knowledge_block",
        new=AsyncMock(return_value=""),
    ):
        out = await build_knowledge_hint("anything", user_id=1)
    assert out == ""


@pytest.mark.asyncio
async def test_build_knowledge_hint_never_raises_on_java_failure():
    """Java unreachable → empty string, no exception."""
    fake_java = AsyncMock()
    fake_java.list_high_priority_knowledge.side_effect = RuntimeError("java down")
    with patch(
        "python_ai_sidecar.clients.java_client.JavaAPIClient",
        return_value=fake_java,
    ), patch(
        "python_ai_sidecar.agent_orchestrator_v2.nodes.load_context._build_knowledge_block",
        new=AsyncMock(side_effect=RuntimeError("embed down")),
    ):
        out = await build_knowledge_hint("anything", user_id=1)
    assert out == ""


@pytest.mark.asyncio
async def test_goal_plan_injects_knowledge_only_when_flag_on(monkeypatch):
    """goal_plan_node calls build_knowledge_hint iff ENABLE_PLAN_KNOWLEDGE on."""
    # Flag OFF — helper must NOT be called.
    monkeypatch.setenv("ENABLE_PLAN_KNOWLEDGE", "0")
    import python_ai_sidecar.config as cfg
    importlib.reload(cfg)
    import python_ai_sidecar.feature_flags as ff
    importlib.reload(ff)

    called = {"n": 0}

    async def _spy(*a, **k):
        called["n"] += 1
        return "\n\nKNOWLEDGE"

    import python_ai_sidecar.agent_builder.graph_build.nodes.goal_plan as gp

    # Make the LLM call fail fast so the node returns early after building user_msg.
    fake_client = AsyncMock()
    fake_client.create.side_effect = RuntimeError("stop after prompt build")

    with patch.object(
        gp, "get_llm_client", return_value=fake_client,
    ), patch(
        "python_ai_sidecar.agent_builder.graph_build.nodes._knowledge_inject.build_knowledge_hint",
        new=_spy,
    ):
        await gp.goal_plan_node({"instruction": "box plot by recipe"})
    assert called["n"] == 0  # flag off → not called

    # Flag ON — helper IS called.
    monkeypatch.setenv("ENABLE_PLAN_KNOWLEDGE", "1")
    importlib.reload(cfg)
    importlib.reload(ff)
    called["n"] = 0
    with patch.object(
        gp, "get_llm_client", return_value=fake_client,
    ), patch(
        "python_ai_sidecar.agent_builder.graph_build.nodes._knowledge_inject.build_knowledge_hint",
        new=_spy,
    ):
        await gp.goal_plan_node({"instruction": "box plot by recipe"})
    assert called["n"] == 1  # flag on → called once
