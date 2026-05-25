"""Tests for InternalProxyLLMClient — custom auth header injection.

InternalProxyLLMClient inherits all message conversion / tool calling logic
from OllamaLLMClient; the only thing this layer adds is `default_headers` on
the OpenAI SDK constructor. So the unit tests focus on constructor wiring +
factory dispatch, not on full request flow (that's already covered by the
OllamaLLMClient pathways).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from python_ai_sidecar.agent_helpers_native import llm_client as llm_mod


@pytest.fixture(autouse=True)
def _reset_cached_client():
    """Each test starts with a fresh factory cache."""
    llm_mod.reset_llm_client()
    yield
    llm_mod.reset_llm_client()


def _fake_openai_module():
    """Build a fake `openai` module so `import openai` inside the client picks
    it up. Returns (fake_module, AsyncOpenAI_mock) so tests can assert on the
    constructor call."""
    AsyncOpenAI = MagicMock(name="AsyncOpenAI")
    AsyncOpenAI.return_value = MagicMock(name="AsyncOpenAIInstance")
    fake = SimpleNamespace(AsyncOpenAI=AsyncOpenAI)
    return fake, AsyncOpenAI


def test_internal_proxy_client_injects_custom_header():
    fake, AsyncOpenAI = _fake_openai_module()
    with patch.dict(sys.modules, {"openai": fake}):
        client = llm_mod.InternalProxyLLMClient(
            base_url="http://llm-gateway:8080",
            api_key="bearer-token-xyz",
            model="gpt-4o",
            header_name="X-API-Key",
            header_value="secret-key-xyz",
        )
    AsyncOpenAI.assert_called_once_with(
        base_url="http://llm-gateway:8080",
        api_key="bearer-token-xyz",
        default_headers={"X-API-Key": "secret-key-xyz"},
    )
    assert client._model == "gpt-4o"


def test_internal_proxy_empty_header_means_no_custom_header():
    """If header_name/value are blank, default_headers should be empty dict
    (not inject an "" key, not omit the kwarg)."""
    fake, AsyncOpenAI = _fake_openai_module()
    with patch.dict(sys.modules, {"openai": fake}):
        llm_mod.InternalProxyLLMClient(
            base_url="http://llm-gateway:8080",
            api_key="bearer-token",
            model="gpt-4o",
            header_name="",
            header_value="",
        )
    AsyncOpenAI.assert_called_once_with(
        base_url="http://llm-gateway:8080",
        api_key="bearer-token",
        default_headers={},
    )


def test_internal_proxy_empty_api_key_falls_back_to_unused_placeholder():
    """Some proxies use header-only auth and ignore Authorization. OpenAI SDK
    still requires api_key to be non-empty — we substitute "unused"."""
    fake, AsyncOpenAI = _fake_openai_module()
    with patch.dict(sys.modules, {"openai": fake}):
        llm_mod.InternalProxyLLMClient(
            base_url="http://llm-gateway:8080",
            api_key="",
            model="gpt-4o",
            header_name="X-API-Key",
            header_value="secret",
        )
    AsyncOpenAI.assert_called_once_with(
        base_url="http://llm-gateway:8080",
        api_key="unused",
        default_headers={"X-API-Key": "secret"},
    )


def test_factory_internal_proxy_dispatch(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "internal-proxy")
    monkeypatch.setenv("INTERNAL_PROXY_BASE_URL", "http://proxy:9000")
    monkeypatch.setenv("INTERNAL_PROXY_API_KEY", "")
    monkeypatch.setenv("INTERNAL_PROXY_HEADER_NAME", "X-API-Key")
    monkeypatch.setenv("INTERNAL_PROXY_HEADER_VALUE", "abc123")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")

    # Reset the settings singleton so our env vars are picked up
    from python_ai_sidecar.pipeline_builder import _sidecar_deps
    _sidecar_deps._settings_singleton = None

    fake, AsyncOpenAI = _fake_openai_module()
    with patch.dict(sys.modules, {"openai": fake}):
        client = llm_mod.get_llm_client()

    assert isinstance(client, llm_mod.InternalProxyLLMClient)
    AsyncOpenAI.assert_called_once_with(
        base_url="http://proxy:9000",
        api_key="unused",
        default_headers={"X-API-Key": "abc123"},
    )


def test_factory_internal_proxy_missing_base_url_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "internal-proxy")
    monkeypatch.setenv("INTERNAL_PROXY_BASE_URL", "")
    monkeypatch.setenv("INTERNAL_PROXY_HEADER_NAME", "X-API-Key")
    monkeypatch.setenv("INTERNAL_PROXY_HEADER_VALUE", "abc")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")

    from python_ai_sidecar.pipeline_builder import _sidecar_deps
    _sidecar_deps._settings_singleton = None

    with pytest.raises(RuntimeError, match="INTERNAL_PROXY_BASE_URL"):
        llm_mod.get_llm_client()
