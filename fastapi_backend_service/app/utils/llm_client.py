"""llm_client.py — Unified LLM client supporting Anthropic Claude and Ollama (OpenAI-compatible).

Usage:
    from app.utils.llm_client import get_llm_client, LLMResponse

    client = get_llm_client()
    resp = await client.create(
        system="You are ...",
        messages=[{"role": "user", "content": "Hello"}],
        max_tokens=1024,
    )
    print(resp.text)

Provider selection is controlled by the LLM_PROVIDER config:
    - "anthropic"  → Anthropic Claude (default)
    - "ollama"     → Any OpenAI-compatible local model (Ollama, vLLM, LMStudio)

Note: The diagnostic agent tool-use loop (diagnostic_service.py) requires
Anthropic's proprietary tool_use blocks. When LLM_PROVIDER="ollama", those
endpoints will fall back to Anthropic automatically (see DiagnosticService).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Response container ────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """Normalized response from any LLM backend."""
    text: str
    stop_reason: str = "end_turn"
    # Raw content list kept for Anthropic tool-use loop compatibility
    # For Ollama responses this is a single-element list [{"type": "text", "text": ...}]
    content: List[Dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# ── Base interface ─────────────────────────────────────────────────────────────

class BaseLLMClient:
    async def create(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        raise NotImplementedError


# ── Anthropic backend ─────────────────────────────────────────────────────────

class AnthropicLLMClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic as _anthropic
        self._client = _anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def create(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        kwargs: Dict[str, Any] = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools

        resp = await self._client.messages.create(**kwargs)

        # Extract first text block (skips ThinkingBlocks)
        text = ""
        for block in resp.content:
            if hasattr(block, "text"):
                text = block.text
                break

        # Normalise content to plain dicts for serialisation safety
        content = []
        for block in resp.content:
            t = getattr(block, "type", None)
            if t == "text":
                content.append({"type": "text", "text": block.text})
            elif t == "tool_use":
                content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif t == "thinking":
                content.append({"type": "thinking", "thinking": getattr(block, "thinking", "")})

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            stop_reason=str(getattr(resp, "stop_reason", "end_turn")),
            content=content,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )


# ── Ollama / OpenAI-compatible backend ───────────────────────────────────────

class OllamaLLMClient(BaseLLMClient):
    """Wraps any OpenAI-compatible endpoint (Ollama, vLLM, LMStudio).

    System prompt is injected as the first message with role='system'
    because OpenAI-compatible APIs don't have a top-level 'system' param.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        import openai as _openai
        self._client = _openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    async def create(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Prepend system message
        full_messages = [{"role": "system", "content": system}] + list(messages)

        kwargs: Dict[str, Any] = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=full_messages,
        )
        # OpenAI-compatible tool calling (function calling format)
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        text = choice.message.content or ""
        stop_reason = choice.finish_reason or "stop"

        content = [{"type": "text", "text": text}]
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            stop_reason=stop_reason,
            content=content,
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )


# ── Factory ───────────────────────────────────────────────────────────────────

_cached_client: Optional[BaseLLMClient] = None


def get_llm_client(force_provider: Optional[str] = None) -> BaseLLMClient:
    """Return a cached LLM client based on LLM_PROVIDER config.

    Args:
        force_provider: Override the config provider for this call only
                        ("anthropic" | "ollama"). Used in tests.
    """
    global _cached_client
    if _cached_client is not None and force_provider is None:
        return _cached_client

    from app.config import get_settings
    settings = get_settings()
    provider = force_provider or settings.LLM_PROVIDER

    if provider == "ollama":
        client = OllamaLLMClient(
            base_url=settings.OLLAMA_BASE_URL,
            api_key=settings.OLLAMA_API_KEY,
            model=settings.OLLAMA_MODEL,
        )
        logger.info("LLM client: Ollama @ %s  model=%s", settings.OLLAMA_BASE_URL, settings.OLLAMA_MODEL)
    else:
        client = AnthropicLLMClient(
            api_key=settings.ANTHROPIC_API_KEY,
            model=settings.LLM_MODEL,
        )
        logger.info("LLM client: Anthropic  model=%s", settings.LLM_MODEL)

    if force_provider is None:
        _cached_client = client
    return client


def reset_llm_client() -> None:
    """Clear cached client — call after config changes (e.g. in tests)."""
    global _cached_client
    _cached_client = None
