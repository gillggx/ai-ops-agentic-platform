"""2026-06-23 — chat orchestrator_v2 llm_call bounded retry (W2).

Ports goal_plan's Fix A to the chat surface: a single transient provider blip
(exception / stop_reason='error' / fully-empty output) must not collapse the
chat turn. One retry recovers it; persistent failure routes to synthesis
gracefully (force_synthesis) instead of crashing the graph.
"""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from python_ai_sidecar.agent_helpers_native import llm_client as mod
from python_ai_sidecar.agent_orchestrator_v2.nodes.llm_call import (
    MAX_LLM_ATTEMPTS,
    llm_call_node,
)


class FakeResp:
    def __init__(self, text="", tool_uses=None, stop_reason="end_turn",
                 finish_reason="stop"):
        self.text = text
        self.content = list(tool_uses or [])
        self.stop_reason = stop_reason
        self.finish_reason = finish_reason
        self.input_tokens = 1
        self.output_tokens = 1
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def create(self, **_kw):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


def _state():
    return {"messages": [HumanMessage(content="EQP-01 狀態?")], "current_iteration": 0,
            "system_text": "you are an ops assistant"}


def _config():
    return {"configurable": {"system_text": "you are an ops assistant", "caller_roles": ()}}


_USABLE_TEXT = FakeResp(text="EQP-01 is Busy.")
_USABLE_TOOL = FakeResp(text="", tool_uses=[
    {"type": "tool_use", "id": "t1", "name": "get_tool_status", "input": {}}])
_PROVIDER_ERR = FakeResp(text="", stop_reason="error", finish_reason="error")
_EMPTY = FakeResp(text="   ", stop_reason="end_turn")


@pytest.mark.asyncio
async def test_provider_error_then_recovers(monkeypatch):
    fake = FakeClient([_PROVIDER_ERR, _USABLE_TEXT])
    monkeypatch.setattr(mod, "get_llm_client", lambda: fake)
    out = await llm_call_node(_state(), _config())
    assert fake.calls == 2
    assert not out.get("force_synthesis")
    assert isinstance(out["messages"][0], AIMessage)
    assert "Busy" in out["messages"][0].content


@pytest.mark.asyncio
async def test_exception_then_recovers_with_tool_call(monkeypatch):
    fake = FakeClient([RuntimeError("provider 503"), _USABLE_TOOL])
    monkeypatch.setattr(mod, "get_llm_client", lambda: fake)
    out = await llm_call_node(_state(), _config())
    assert fake.calls == 2
    assert not out.get("force_synthesis")
    assert out["messages"][0].tool_calls and out["messages"][0].tool_calls[0]["name"] == "get_tool_status"


@pytest.mark.asyncio
async def test_empty_output_then_recovers(monkeypatch):
    fake = FakeClient([_EMPTY, _USABLE_TEXT])
    monkeypatch.setattr(mod, "get_llm_client", lambda: fake)
    out = await llm_call_node(_state(), _config())
    assert fake.calls == 2
    assert not out.get("force_synthesis")


@pytest.mark.asyncio
async def test_persistent_failure_routes_to_synthesis(monkeypatch):
    fake = FakeClient([_PROVIDER_ERR])
    monkeypatch.setattr(mod, "get_llm_client", lambda: fake)
    out = await llm_call_node(_state(), _config())
    assert fake.calls == MAX_LLM_ATTEMPTS  # bounded, no infinite retry
    assert out.get("force_synthesis") is True
    assert "provider_error" in out["messages"][0].content


@pytest.mark.asyncio
async def test_usable_first_try_no_retry(monkeypatch):
    fake = FakeClient([_USABLE_TEXT])
    monkeypatch.setattr(mod, "get_llm_client", lambda: fake)
    out = await llm_call_node(_state(), _config())
    assert fake.calls == 1
    assert not out.get("force_synthesis")
    # finish_reason now surfaced on the turn metadata (observability)
    assert "finish_reason" in out["messages"][0].response_metadata
