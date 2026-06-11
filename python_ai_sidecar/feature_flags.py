"""Per-request feature flag overrides.

Performance flags are read at startup from env (see ``config.py``):

  - ``ENABLE_PROMPT_CACHE`` — Anthropic / OpenRouter prompt cache markers
  - ``ENABLE_AUTO_SIGNAL`` — auto commit_pick after add_node (sub-phase shortcut)
  - ``ENABLE_ATOMIC_ADD_CONNECT`` — accept upstream=[...] in add_node and atomically
    add + connect in one tool call (saves 1 LLM round per node)
  - ``ENABLE_AUTO_VERIFIER`` — auto-trigger run_verifier when phase-terminal block
    lands on canvas (saves 1 LLM round per phase)
  - ``ENABLE_STRICT_TOOL_ID`` — block_process_history rejects tool_id='ALL'/'*'
    sentinel values at build-time, forcing agent into fan-out or mcp_call pattern

Callers read the *effective* flag via the ``is_*_enabled()`` helpers so a single
request can be steered without restarting the sidecar — useful for A/B
verification and per-skill rollout.

Override protocol: HTTP header ``X-Feature-Flags`` carrying comma-separated
``name:value`` pairs, e.g.

    X-Feature-Flags: prompt_cache:on,auto_signal:off,atomic_add_connect:on

Recognised values: ``on/off``, ``1/0``, ``true/false``, ``yes/no``. Unknown
flags are silently ignored (forward-compat). Parsing failures fall back to
the env-default — never raise.
"""

from __future__ import annotations

from contextvars import ContextVar

from .config import CONFIG

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

_KNOWN_FLAGS = (
    "prompt_cache",
    "auto_signal",
    "atomic_add_connect",
    "auto_verifier",
    "strict_tool_id",
)

# Per-request override map. Empty dict ⇒ no override, fall back to CONFIG.
_override_ctx: ContextVar[dict[str, bool]] = ContextVar(
    "feature_flag_override", default={}
)


def parse_feature_flags_header(value: str) -> dict[str, bool]:
    """Parse an ``X-Feature-Flags`` header value into a ``{name: bool}`` map.

    Returns an empty dict on any parse failure — callers should treat an
    empty result as "no override, use defaults".
    """
    out: dict[str, bool] = {}
    if not value:
        return out
    for part in value.split(","):
        if ":" not in part:
            continue
        name, _, raw = part.partition(":")
        name = name.strip().lower()
        raw = raw.strip().lower()
        if name not in _KNOWN_FLAGS:
            continue
        if raw in _TRUE:
            out[name] = True
        elif raw in _FALSE:
            out[name] = False
    return out


def set_request_overrides(overrides: dict[str, bool]) -> object:
    """Bind overrides for the current request/task. Returns a token usable
    with ``reset_request_overrides`` (or simply discard at request end —
    asyncio task scope cleans up automatically).
    """
    return _override_ctx.set(dict(overrides))


def reset_request_overrides(token: object) -> None:
    _override_ctx.reset(token)  # type: ignore[arg-type]


def _effective(name: str, default: bool) -> bool:
    override = _override_ctx.get()
    if name in override:
        return override[name]
    return default


def is_prompt_cache_enabled() -> bool:
    return _effective("prompt_cache", CONFIG.enable_prompt_cache)


def is_auto_signal_enabled() -> bool:
    return _effective("auto_signal", CONFIG.enable_auto_signal)


def is_atomic_add_connect_enabled() -> bool:
    return _effective("atomic_add_connect", CONFIG.enable_atomic_add_connect)


def is_auto_verifier_enabled() -> bool:
    return _effective("auto_verifier", CONFIG.enable_auto_verifier)


def is_strict_tool_id_enabled() -> bool:
    return _effective("strict_tool_id", CONFIG.enable_strict_tool_id)
