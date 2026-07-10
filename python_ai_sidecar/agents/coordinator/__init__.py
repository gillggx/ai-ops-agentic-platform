"""Coordinator — the conversation-first operations agent (public API).

Implementation: python_ai_sidecar/agent_orchestrator_v2/chat_agent_loop.py
(physical move pending; import from THIS package, not from there).
"""
from python_ai_sidecar.agent_orchestrator_v2.chat_agent_loop import (  # noqa: F401
    is_chat_agent_loop_enabled,
    run_chat_agent,
)

__all__ = ["run_chat_agent", "is_chat_agent_loop_enabled"]
