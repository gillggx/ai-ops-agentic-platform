"""S3 empty-rate rollup tests (W2 governance).

After every LLM completion the client fires a detached POST to Java
`/internal/llm-usage/increment`. Hard rules under test:
- payload shape: {model, empty, error, input_tokens, output_tokens, cache_read}
- fail-open: Java down / no loop NEVER breaks the LLM call
- detached: _observe_llm_usage returns synchronously; the POST rides a task.
"""
from __future__ import annotations

import asyncio

import httpx

from python_ai_sidecar.agent_helpers_native.llm_client import (
    LLMResponse,
    _observe_llm_usage,
    _report_llm_exception,
)


class _FakeAsyncClient:
    """Fake httpx transport capturing rollup POSTs (or exploding on demand)."""

    captured: list[tuple[str, dict, dict]] = []
    fail: bool = False

    def __init__(self, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        if _FakeAsyncClient.fail:
            raise RuntimeError("java down")
        _FakeAsyncClient.captured.append((url, json, headers))

        class _R:
            status_code = 200

        return _R()


def _install(monkeypatch, fail: bool = False):
    _FakeAsyncClient.captured = []
    _FakeAsyncClient.fail = fail
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


async def _drain_tasks():
    """Let the detached rollup task run to completion."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def test_rollup_payload_empty_completion(monkeypatch):
    _install(monkeypatch)

    async def scenario():
        resp = LLMResponse(text="   ", finish_reason="stop", content=[],
                           input_tokens=120, output_tokens=0,
                           cache_read_input_tokens=7)
        out = _observe_llm_usage(resp, model="z-ai/glm-5.2")
        assert out is resp  # completion path untouched
        await _drain_tasks()

    asyncio.run(scenario())
    assert len(_FakeAsyncClient.captured) == 1
    url, payload, headers = _FakeAsyncClient.captured[0]
    assert url.endswith("/internal/llm-usage/increment")
    assert payload == {
        "model": "z-ai/glm-5.2",
        "empty": True,
        "error": False,
        "input_tokens": 120,
        "output_tokens": 0,
        "cache_read": 7,
    }
    assert "X-Internal-Token" in headers


def test_rollup_not_empty_when_tool_calls_or_text(monkeypatch):
    _install(monkeypatch)

    async def scenario():
        # tool_use with no text is a NORMAL completion, not empty
        _observe_llm_usage(LLMResponse(
            text="", finish_reason="stop",
            content=[{"type": "tool_use", "id": "t1", "name": "add_node",
                      "input": {}}],
            input_tokens=10, output_tokens=5), model="m")
        # plain text is not empty either
        _observe_llm_usage(LLMResponse(
            text="ok", finish_reason="end_turn", content=[],
            input_tokens=10, output_tokens=2), model="m")
        await _drain_tasks()

    asyncio.run(scenario())
    assert [p["empty"] for _, p, _ in _FakeAsyncClient.captured] == [False, False]
    assert [p["error"] for _, p, _ in _FakeAsyncClient.captured] == [False, False]


def test_rollup_flags_provider_error_finish_reason(monkeypatch):
    _install(monkeypatch)

    async def scenario():
        _observe_llm_usage(LLMResponse(
            text="", finish_reason="error", content=[],
            input_tokens=0, output_tokens=0), model="m")
        await _drain_tasks()

    asyncio.run(scenario())
    _, payload, _ = _FakeAsyncClient.captured[0]
    assert payload["error"] is True
    # 'error' finish is not the normal-stop family → not counted as empty
    assert payload["empty"] is False


def test_rollup_on_raised_provider_call(monkeypatch):
    _install(monkeypatch)

    async def scenario():
        _report_llm_exception("m-exploded")
        await _drain_tasks()

    asyncio.run(scenario())
    _, payload, _ = _FakeAsyncClient.captured[0]
    assert payload == {"model": "m-exploded", "empty": False, "error": True,
                       "input_tokens": 0, "output_tokens": 0, "cache_read": 0}


def test_rollup_fail_open_java_down(monkeypatch):
    """Transport failure is swallowed — the LLM completion is unaffected."""
    _install(monkeypatch, fail=True)

    async def scenario():
        resp = LLMResponse(text="answer", finish_reason="stop", content=[],
                           input_tokens=1, output_tokens=1)
        out = _observe_llm_usage(resp, model="m")
        assert out is resp
        await _drain_tasks()  # must not raise out of the task

    asyncio.run(scenario())  # no exception ⇒ fail-open holds
    assert _FakeAsyncClient.captured == []


def test_rollup_no_event_loop_is_noop(monkeypatch):
    """Sync context (no running loop): rollup silently skipped, never raises."""
    _install(monkeypatch)
    resp = LLMResponse(text="x", finish_reason="stop", content=[])
    out = _observe_llm_usage(resp, model="m")
    assert out is resp
    assert _FakeAsyncClient.captured == []
