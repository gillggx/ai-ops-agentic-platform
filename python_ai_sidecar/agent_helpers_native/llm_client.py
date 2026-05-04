"""llm_client.py — Unified LLM client supporting Anthropic Claude and Ollama (OpenAI-compatible).

Usage:
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client, LLMResponse

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
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

# Phase 2-A: LangSmith tracing — @traceable is a no-op when LANGSMITH_API_KEY
# is unset, so this is safe to apply unconditionally.
try:
    from langsmith import traceable
except ImportError:  # langsmith not installed → provide a no-op fallback
    def traceable(*args, **kwargs):  # type: ignore[no-redef]
        def _decorator(fn):
            return fn
        # Support both @traceable and @traceable(...)
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return _decorator

logger = logging.getLogger(__name__)


def _parse_xml_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Parse Anthropic-style XML tool calls from text content.

    Handles models (Kimi K2, etc.) that output tool calls as XML instead of
    using the function calling API.

    Supported formats:
        <tool_call>
        <invoke name="tool_name">
        <parameter name="key">value</parameter>
        </invoke>
        </tool_call>

        or without outer <tool_call> wrapper:
        <invoke name="tool_name">...</invoke>
    """
    calls: List[Dict[str, Any]] = []

    def _parse_invoke_block(invoke_body: str, tool_name: str) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        for p_match in re.finditer(
            r'<parameter\s+name="([^"]+)">([\s\S]*?)</parameter>', invoke_body
        ):
            param_name = p_match.group(1)
            param_value = p_match.group(2).strip()
            try:
                params[param_name] = json.loads(param_value)
            except (json.JSONDecodeError, ValueError):
                params[param_name] = param_value
        return {
            "type": "tool_use",
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "name": tool_name,
            "input": params,
        }

    # Try <tool_call>...<invoke name="...">...</invoke>...</tool_call>
    for tc_match in re.finditer(r"<tool_call>([\s\S]*?)</tool_call>", text):
        tc_body = tc_match.group(1)
        name_match = re.search(r'<invoke\s+name="([^"]+)"', tc_body)
        if name_match:
            calls.append(_parse_invoke_block(tc_body, name_match.group(1)))

    if calls:
        return calls

    # Fallback: bare <invoke name="...">...</invoke> without <tool_call> wrapper
    for inv_match in re.finditer(
        r'<invoke\s+name="([^"]+)">([\s\S]*?)</invoke>', text
    ):
        calls.append(_parse_invoke_block(inv_match.group(0), inv_match.group(1)))

    return calls


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
    # Anthropic prompt cache stats (Phase 2-A): cache_creation is the one-time
    # cost to write a cacheable block ($3.75/MTok); cache_read is the discount
    # we pay every iteration after that ($0.30/MTok vs $3/MTok input). Both
    # are 0 on OpenAI-compat providers that don't support caching.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


# ── Base interface ─────────────────────────────────────────────────────────────

class BaseLLMClient:
    async def create(
        self,
        *,
        system: "str | List[Dict[str, Any]]",
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Create an LLM completion.

        `system` accepts either a plain string OR an Anthropic content-block
        list (e.g. `[{"type":"text","text":"...","cache_control":{...}}]`).
        Subclasses for non-Anthropic providers MUST flatten the list back to
        string and drop unsupported fields like `cache_control`.

        `tools[-1]["cache_control"]` (Anthropic prompt caching) is similarly
        consumed by AnthropicLLMClient and ignored by OpenAI-compat clients.
        """
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

    @traceable(run_type="llm", name="anthropic_create")
    async def create(
        self,
        *,
        system: "str | List[Dict[str, Any]]",
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Anthropic accepts both string and content-block list for `system`.
        # Caller is responsible for placing cache_control breakpoints; we just
        # pass through. Same for `tools[i]["cache_control"]`.
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
        # 2026-05-04 cache debug instrumentation: log per-call so we can spot
        # cache misses across a session. Cheap (one log line per LLM call).
        if usage is not None:
            import logging as _lg
            _lg.getLogger("python_ai_sidecar.cache_debug").info(
                "llm_create: in=%d out=%d cache_create=%d cache_read=%d sys_chars=%d msgs=%d tools=%d",
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                getattr(usage, "cache_creation_input_tokens", 0) or 0,
                getattr(usage, "cache_read_input_tokens", 0) or 0,
                len(system) if isinstance(system, str)
                  else sum(len(b.get("text", "")) for b in (system or []) if isinstance(b, dict)),
                len(messages or []),
                len(tools or []),
            )
        return LLMResponse(
            text=text,
            stop_reason=str(getattr(resp, "stop_reason", "end_turn")),
            content=content,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0 if usage else 0,
            cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0 if usage else 0,
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

    @staticmethod
    def _flatten_system(system: "str | List[Dict[str, Any]]") -> str:
        """Anthropic accepts a list of content blocks (with cache_control);
        OpenAI-compat APIs only take a single string. Concatenate the text
        fields and silently drop `cache_control` / non-text blocks."""
        if isinstance(system, str):
            return system
        if isinstance(system, list):
            parts: List[str] = []
            for blk in system:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    parts.append(blk.get("text", "") or "")
            return "\n".join(parts)
        return str(system or "")

    def _to_openai_messages(
        self,
        system: "str | List[Dict[str, Any]]",
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert Anthropic-format messages to OpenAI format.

        Handles:
        - Anthropic assistant tool_use blocks → OpenAI tool_calls
        - Anthropic user tool_result blocks → OpenAI role=tool messages
        - Plain text content → pass through unchanged
        """
        system_str = self._flatten_system(system)
        result: List[Dict[str, Any]] = [{"role": "system", "content": system_str}]

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

    @traceable(run_type="llm", name="ollama_create")
    async def create(
        self,
        *,
        system: "str | List[Dict[str, Any]]",
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Prepend a concise function-calling mandate when tools are provided.
        # Qwen3 / local models tend to output JSON tool calls as plain text
        # instead of using the function calling API — this instruction fixes it.
        # Flatten cache-block list down to string first; OpenAI-compat APIs
        # only accept a string `system`.
        system_str = self._flatten_system(system)
        effective_system = system_str
        if tools:
            effective_system = (
                "IMPORTANT: You MUST use the function calling API (tool_calls) to invoke tools. "
                "Do NOT output tool calls as JSON text, XML, or any other text format.\n"
                "【工具使用規則】必須透過 function calling API 呼叫工具，禁止以任何文字格式輸出工具呼叫。\n\n"
            ) + system_str

        full_messages = self._to_openai_messages(effective_system, messages)

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
            kwargs["tool_choice"] = "auto"
            # Disable extended thinking for Qwen3 / reasoning models so they use
            # the function calling API instead of generating JSON inside <think> blocks.
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        # Normalise OpenAI finish_reason → Anthropic stop_reason convention
        _finish = choice.finish_reason or "stop"
        stop_reason = "end_turn" if _finish in ("stop", "length", "eos", "model_length", "content_filter") else _finish

        import sys as _sys
        _orig_content = choice.message.content or ""
        _tc_count = len(choice.message.tool_calls) if choice.message.tool_calls else 0
        print(f"[LLM-DBG] finish={_finish!r} tool_calls={_tc_count} content_len={len(_orig_content)} content_preview={_orig_content[:300]!r}", file=_sys.stderr, flush=True)
        # Show full message fields to detect reasoning_content or other hidden fields
        try:
            _msg_dict = choice.message.model_dump()
            _reasoning = _msg_dict.get("reasoning_content") or _msg_dict.get("reasoning")
            print(f"[LLM-DBG2] reasoning_raw={_reasoning!r}", file=_sys.stderr, flush=True)
        except Exception as _e:
            print(f"[LLM-DBG2] model_dump failed: {_e}", file=_sys.stderr, flush=True)

        # Strip Qwen3 / DeepSeek <think>...</think> reasoning blocks from content.
        # These appear when the model "thinks" in text mode and leak partial JSON
        # tool-call fragments into choice.message.content.
        raw_content = _orig_content
        raw_content = re.sub(r"<think>[\s\S]*?</think>", "", raw_content, flags=re.IGNORECASE).strip()

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
            # No function-calling tool_calls — check for XML tool calls first.
            # Kimi K2 and models trained on Anthropic's format output tool calls as
            # XML text (<tool_call><invoke name="...">...</invoke></tool_call>)
            # instead of using the OpenAI function calling API.
            xml_calls = _parse_xml_tool_calls(raw_content)
            if xml_calls:
                stop_reason = "tool_use"
                text = ""
                content.extend(xml_calls)
            else:
                # Plain text response.
                # Additional guard: discard broken JSON tool-call fragments that
                # Qwen3 / reasoning models leak into content alongside thinking blocks.
                _is_garbage = (
                    raw_content.startswith('arguments"')
                    or raw_content.startswith('"arguments"')
                    or (raw_content.startswith('"') and '": {' in raw_content[:40] and raw_content.endswith("}}"))
                )
                text = "" if _is_garbage else raw_content
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

    from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
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
