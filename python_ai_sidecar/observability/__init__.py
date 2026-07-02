"""Agent observability — episode/step recording (V69).

See docs/MULTI_AGENT_OBSERVABILITY_SPEC.md.
"""
from python_ai_sidecar.observability.episode_recorder import (
    EpisodeRecorder,
    get_current_agent,
    get_current_recorder,
    make_recorder,
    reset_current_agent,
    set_current_agent,
    set_current_recorder,
)

__all__ = [
    "EpisodeRecorder",
    "get_current_agent",
    "get_current_recorder",
    "make_recorder",
    "reset_current_agent",
    "set_current_agent",
    "set_current_recorder",
]
