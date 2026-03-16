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
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Response container ────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """Normalized response from any LLM backend."""
    text: str
    stop_reason: str = "end_turn"
    # Raw content list kept for tool-use loop compatibility
    # Each element is a plain dict: {"type": "text"|"tool_use"|"thinking", ...}
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

    async def stream(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        raise NotImplementedError
        # Make this a proper async generator
        if False:
            yield ""


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

    async def stream(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Yield text chunks from Anthropic streaming API."""
        async with self._client.messages.stream(
            model=self._model,
            system=system,
            max_tokens=max_tokens,
            messages=messages,
        ) as s:
            async for text in s.text_stream:
                yield text


# ── Ollama / OpenAI-compatible backend ───────────────────────────────────────

class OllamaLLMClient(BaseLLMClient):
    """Wraps any OpenAI-compatible endpoint (Ollama, vLLM, LMStudio).

    System prompt is injected as the first message with role='system'
    because OpenAI-compatible APIs don't have a top-level 'system' param.
    Anthropic-format messages (tool_use / tool_result blocks) are converted
    to OpenAI function-calling format transparently.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        import openai as _openai
        self._client = _openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model

    def _to_openai_messages(
        self,
        system: str,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI format.

        Handles:
        - Anthropic assistant tool_use blocks → OpenAI tool_calls
        - Anthropic user tool_result blocks → OpenAI role=tool messages
        - Plain text content → pass through unchanged
        """
        result: List[Dict[str, Any]] = [{"role": "system", "content": system}]

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # ── Assistant message ──────────────────────────────────────
            if role == "assistant":
                if isinstance(content, list):
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text_parts.append(block.get("text", ""))
                        elif btype == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(
                                        block.get("input", {}),
                                        ensure_ascii=False,
                                    ),
                                },
                            })
                    oai_msg: Dict[str, Any] = {"role": "assistant"}
                    if text_parts:
                        oai_msg["content"] = "\n".join(text_parts)
                    else:
                        oai_msg["content"] = None
                    if tool_calls:
                        oai_msg["tool_calls"] = tool_calls
                    result.append(oai_msg)
                else:
                    result.append({"role": "assistant", "content": content or ""})

            # ── User message — may contain tool_result blocks ──────────
            elif role == "user":
                if isinstance(content, list):
                    # Check if this is a tool_result message
                    has_tool_result = any(
                        isinstance(b, dict) and b.get("type") == "tool_result"
                        for b in content
                    )
                    if has_tool_result:
                        # Expand each tool_result into a separate role=tool message
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_result":
                                tool_content = block.get("content", "")
                                result.append({
                                    "role": "tool",
                                    "tool_call_id": block.get("tool_use_id", ""),
                                    "content": tool_content if isinstance(tool_content, str)
                                               else json.dumps(tool_content, ensure_ascii=False),
                                })
                            elif block.get("type") == "text":
                                result.append({
                                    "role": "user",
                                    "content": block.get("text", ""),
                                })
                    else:
                        # Regular user content list (text blocks)
                        text_parts = [
                            b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        ]
                        result.append({"role": "user", "content": "\n".join(text_parts)})
                else:
                    result.append({"role": "user", "content": content or ""})

            else:
                # Pass through other roles unchanged
                result.append({"role": role, "content": content or ""})

        return result

    async def create(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        full_messages = self._to_openai_messages(system, messages)

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

        # Normalise OpenAI finish_reason → Anthropic stop_reason convention
        _finish = choice.finish_reason or "stop"
        stop_reason = "end_turn" if _finish in ("stop", "length", "eos", "model_length", "content_filter") else _finish

        # Build normalised content list
        content: List[Dict[str, Any]] = []

        # Handle tool_calls in response
        # When tool_calls are present, ignore content text — Qwen3/some models
        # spuriously put JSON fragments or reasoning in content alongside tool_calls.
        if choice.message.tool_calls:
            stop_reason = "tool_use"
            text = ""   # discard any text content when model is making tool calls
            for tc in choice.message.tool_calls:
                try:
                    tc_input = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    tc_input = {}
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": tc_input,
                })
        else:
            # No tool calls — plain text response
            text = choice.message.content or ""
            if text:
                content.append({"type": "text", "text": text})

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            stop_reason=stop_reason,
            content=content,
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        )

    async def stream(
        self,
        *,
        system: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """Yield text chunks from OpenAI-compatible streaming API."""
        full_messages = self._to_openai_messages(system, messages)
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=full_messages,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


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
