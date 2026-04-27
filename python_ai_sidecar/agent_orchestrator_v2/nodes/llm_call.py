"""llm_call node — invokes the LLM via the existing multi-provider client.

Uses the v1 BaseLLMClient.create() API, then converts the response into
LangChain AIMessage with tool_calls so the graph can route properly.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from langchain_core.runnables import RunnableConfig

from langchain_core.messages import AIMessage, ToolMessage

from python_ai_sidecar.pipeline_builder._sidecar_deps import get_settings
from python_ai_sidecar.agent_orchestrator_v2.state import MAX_ITERATIONS
from python_ai_sidecar.agent_helpers.tool_dispatcher import TOOL_SCHEMAS

# Tools hidden from LLM — still available internally
# execute_mcp: internal only (skill code uses it)
# query_data: replaced by plan_pipeline
# execute_analysis: replaced by plan_pipeline Stage 4+5
# propose_pipeline_patch: Phase 5-UX-6 — retired in favor of build_pipeline_live
#   (schema kept in tool_dispatcher for future copilot-mode reactivation)
_LLM_HIDDEN_TOOLS = {"execute_mcp", "query_data", "execute_analysis", "propose_pipeline_patch"}
# Phase 4-C: if PIPELINE_ONLY_MODE is on, additionally hide execute_skill so
# Agent is forced to use build_pipeline_live (or answer with text for knowledge Q).
_PIPELINE_ONLY_EXTRA_HIDDEN = {"execute_skill"}

# Phase v1.3 P0 — ON_DUTY tool restriction.
# ON_DUTY users should only be able to consume *published* skills + read raw
# data; they cannot author new pipelines or write to global memory. Anything
# in this set is removed from the LLM-visible catalog when caller's only role
# is ON_DUTY (PE / IT_ADMIN bypass via RoleHierarchy).
_ON_DUTY_HIDDEN_TOOLS = {
    "build_pipeline_live",
    "propose_pipeline_patch",
    "save_memory",
    "update_user_preference",
    "draft_skill",
    "build_skill",
    "draft_mcp",
    "build_mcp",
    "draft_routine_check",
    "draft_event_skill_link",
    "patch_skill_raw",
    "patch_mcp",
}


def _is_on_duty_only(roles: tuple[str, ...] | list[str] | None) -> bool:
    """True iff caller is strictly ON_DUTY (no PE / IT_ADMIN authority).

    Empty roles are treated as ON_DUTY (fail-closed) so a misconfigured
    JWT can never elevate a user beyond the most-restricted view.
    """
    if not roles:
        return True
    role_set = {r.upper() for r in roles}
    if "IT_ADMIN" in role_set or "PE" in role_set:
        return False
    return "ON_DUTY" in role_set or len(role_set) == 0


def _visible_tools(roles: tuple[str, ...] | list[str] | None = None) -> List[Dict[str, Any]]:
    """Build LLM-visible tool list, honoring PIPELINE_ONLY_MODE + caller role.

    Settings flips are read at call time so hot-reload doesn't need a process
    restart; role gating is fail-closed (empty = ON_DUTY).
    """
    hidden = set(_LLM_HIDDEN_TOOLS)
    try:
        if get_settings().PIPELINE_ONLY_MODE:
            hidden |= _PIPELINE_ONLY_EXTRA_HIDDEN
    except Exception:
        # Settings may not be initialised in some test paths — default safe
        pass
    if _is_on_duty_only(roles):
        hidden |= _ON_DUTY_HIDDEN_TOOLS
    return [t for t in TOOL_SCHEMAS if t["name"] not in hidden]


# Backward-compat alias (some callers import LLM_TOOL_SCHEMAS directly).
LLM_TOOL_SCHEMAS = [t for t in TOOL_SCHEMAS if t["name"] not in _LLM_HIDDEN_TOOLS]

logger = logging.getLogger(__name__)


def _langchain_messages_to_v1(messages: list, system_text: str) -> tuple[str, list]:
    """Convert LangChain message list → v1 (system, messages) format.

    v1 client expects:
      system: str
      messages: [{"role": "user"|"assistant"|..., "content": str|list}]
    """
    v1_messages = []
    for msg in messages:
        if hasattr(msg, "type"):
            role = "user" if msg.type == "human" else "assistant" if msg.type == "ai" else msg.type
        else:
            role = msg.get("role", "user") if isinstance(msg, dict) else "user"

        content = msg.content if hasattr(msg, "content") else str(msg)

        # If it's an AIMessage with tool_calls, we need to include tool_use blocks
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            content_blocks = []
            if content:
                content_blocks.append({"type": "text", "text": content})
            for tc in msg.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "input": tc.get("args", {}),
                })
            v1_messages.append({"role": "assistant", "content": content_blocks})
        elif isinstance(msg, ToolMessage):
            v1_messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                ],
            })
        else:
            v1_messages.append({"role": role, "content": content})

    return system_text, v1_messages


def _v1_response_to_tool_calls(response) -> List[Dict[str, Any]]:
    """Extract tool_calls from v1 LLMResponse.content."""
    tool_calls = []
    for block in (response.content or []):
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "args": block.get("input", {}),
            })
    return tool_calls


async def llm_call_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Call the LLM and return an AIMessage (with or without tool_calls)."""
    from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

    llm = get_llm_client()
    system_text = state.get("system_text") or config["configurable"].get("system_text", "")
    # Part A: when the user just resolved a clarify card, surface the chosen
    # intent to the LLM as a hint so it goes straight to the right tool.
    intent_hint = state.get("intent_hint")
    if intent_hint:
        system_text += (
            f"\n\n# User intent hint (from clarify card)\n"
            f"User picked **{intent_hint}** — focus the response on that direction; "
            f"don't ask again, don't go broader.\n"
        )
    messages = state.get("messages", [])
    iteration = state.get("current_iteration", 0) + 1

    # Convert LangChain messages → v1 format. _langchain_messages_to_v1 may
    # absorb a leading SystemMessage and override system_text — keep its
    # output as the source of truth for the cacheable block below.
    system, v1_messages = _langchain_messages_to_v1(messages, system_text)

    # Phase 2-A: wrap system in an Anthropic content-block list with a single
    # ephemeral cache breakpoint at the end so the catalog + tool defs +
    # role + plan-first + use-snapshot rules become cacheable. After the first
    # iteration in a chat turn, subsequent iterations hit the cache and the
    # 25k token static prefix costs ~10× less. OpenAI-compat clients flatten
    # this back to string and ignore cache_control (see OllamaLLMClient).
    cacheable_system = [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
    ]
    # Same idea for tool defs — Anthropic lets you mark cache_control on the
    # *last* tool to cache the whole list. See:
    # https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching#caching-tool-definitions
    # We mutate a copy so we don't pollute the shared TOOL_SCHEMAS registry.

    # Phase 4-C: call _visible_tools() so PIPELINE_ONLY_MODE flag is consulted
    # at invocation time (supports env/config hot-reload without process restart).
    # Phase v1.3 P0: caller's roles flow through config so ON_DUTY users get a
    # restricted catalog (no build_pipeline_live, no memory writes, etc.).
    caller_roles = config["configurable"].get("caller_roles") or ()
    visible_tools = _visible_tools(caller_roles)
    # Phase v1.3 P0 debug — confirm role gating actually fires.
    logger.info(
        "llm_call: caller_roles=%s visible_tool_count=%d hidden_role_tools=%s",
        caller_roles,
        len(visible_tools),
        [t for t in ("build_pipeline_live", "draft_skill", "save_memory")
         if t not in {x["name"] for x in visible_tools}],
    )

    # Phase 2-A cont'd: clone the tool list and stamp cache_control on the
    # last tool so Anthropic caches the entire tool block alongside system.
    # Mutating in-place would persist into the shared TOOL_SCHEMAS registry
    # across iterations (already happens naturally but explicit is safer).
    cacheable_tools = [dict(t) for t in visible_tools]
    if cacheable_tools:
        cacheable_tools[-1] = {
            **cacheable_tools[-1],
            "cache_control": {"type": "ephemeral"},
        }

    try:
        response = await llm.create(
            system=cacheable_system,
            messages=v1_messages,
            max_tokens=8192,
            tools=cacheable_tools,
        )
    except Exception as exc:
        logger.exception("LLM call failed at iteration %d", iteration)
        # Return a synthetic error message so the graph can route to synthesis
        return {
            "messages": [AIMessage(content=f"LLM 呼叫失敗: {exc}")],
            "current_iteration": iteration,
            "force_synthesis": True,
        }

    # Build AIMessage from v1 response
    tool_calls = _v1_response_to_tool_calls(response)

    # Extract text content (strip thinking blocks same as v1)
    text = response.text or ""

    ai_msg = AIMessage(
        content=text,
        tool_calls=tool_calls if tool_calls else [],
        response_metadata={
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "stop_reason": response.stop_reason,
        },
    )

    return {
        "messages": [ai_msg],
        "current_iteration": iteration,
    }
