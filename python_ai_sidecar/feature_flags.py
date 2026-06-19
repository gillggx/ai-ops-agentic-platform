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
  - ``ENABLE_NO_DUPLICATE_NODE`` — add_node rejects when canvas already has an
    orphan (no downstream edges) node with identical (block_id, params). Catches
    KIMI's "echo" behaviour without false-positives on parallel-chain DAGs.
  - ``ENABLE_RICH_CANVAS_SNAPSHOT`` — mid-phase prompt becomes context-aware per
    sub-phase (pick/construct/tune); construct+tune rounds show upstream output
    columns + sample so params are filled from real data, not guessed.
  - ``ENABLE_PLAN_KNOWLEDGE`` — inject agent_knowledge (high-priority + RAG) into
    the v30 builder goal_plan_node (was dead for v30 — only legacy plan_node read it).
  - ``ENABLE_STRICT_PHASE_OUTPUT`` — finalize_node fails the build with
    ``failed_missing_output`` when the plan's final phase wants a presentation
    kind (chart/table/scalar/alarm) but no terminal block covers it. Plan-level
    deliverable fact check, not a prompt rule.
  - ``ENABLE_EXECUTE_KNOWLEDGE`` (V58) — phase_loop injects execute-layer RAG
    knowledge (agent_knowledge applies_to ∈ {execute,both}) at the pick
    sub-phase, so block-choice rules reach the layer that picks the block.
  - ``ENABLE_LAYERED_PLAN_KNOWLEDGE`` (V58) — goal_plan retrieves only the plan
    slice and shrinks the always-on dump to always_on=true core + RAG. OFF →
    legacy (all high, no layer filter) preserved exactly.
  - ``ENABLE_PRESENTATION_LOOKAHEAD`` (2026-06-17) — after plan-confirm, resolve
    each presentation phase's likely block + its `## Inputs` contract and inject
    that contract as the target for the upstream handling (transform) phase, so
    the handling agent aims at a concrete output shape (downstream-driven) instead
    of a vague "transform". OFF → no resolver node, behaviour unchanged.
  - ``ENABLE_RICH_SCHEMA_VALUES`` (2026-06-17) — runtime schema lists the TRUE
    distinct values of low-cardinality string columns (computed over the full
    node output, not the 5-row sample), so the agent can write filter/groupby
    params without an extra inspect_node_output. Also folds the just-added
    node's runtime schema into the post-add tool_result so the agent sees what
    it produced without re-inspecting. OFF → sample-only inference (current).
  - ``ENABLE_ORPHAN_RESOLVE`` (2026-06-18) — before finalize, if any node is
    fully disconnected (no inbound AND no outbound edge), route back to the
    agent to decide connect-or-remove instead of silently failing the build
    with failed_structural. Fixes spc-ooc's stray-orphan failure. OFF →
    orphan fails at finalize (current).
  - ``ENABLE_GOAL_AWARE_MATCHING`` (2026-06-18) — the MATCHING BLOCKS section is
    re-ranked by relevance to the phase GOAL (not just expected kind), top
    candidate marked [best fit]. Stops adjacent same-kind phases (two raw_data:
    list-machines vs fetch-data) showing identical candidate lists that lure the
    agent into the wrong-phase block. Re-ranked, never removed. OFF → kind-only.

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
    "no_duplicate_node",
    "rich_canvas_snapshot",
    "plan_knowledge",
    "strict_phase_output",
    "construct_param_doc",
    "strict_phase_verify",
    "next_memo",
    "execute_knowledge",
    "layered_plan_knowledge",
    "interactive_brief",
    "presentation_lookahead",
    "rich_schema_values",
    "orphan_resolve",
    "goal_aware_matching",
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


def is_no_duplicate_node_enabled() -> bool:
    return _effective("no_duplicate_node", CONFIG.enable_no_duplicate_node)


def is_rich_canvas_snapshot_enabled() -> bool:
    return _effective("rich_canvas_snapshot", CONFIG.enable_rich_canvas_snapshot)


def is_plan_knowledge_enabled() -> bool:
    return _effective("plan_knowledge", CONFIG.enable_plan_knowledge)


def is_strict_phase_output_enabled() -> bool:
    return _effective("strict_phase_output", CONFIG.enable_strict_phase_output)


def is_construct_param_doc_enabled() -> bool:
    return _effective("construct_param_doc", CONFIG.enable_construct_param_doc)


def is_strict_phase_verify_enabled() -> bool:
    return _effective("strict_phase_verify", CONFIG.enable_strict_phase_verify)


def is_next_memo_enabled() -> bool:
    return _effective("next_memo", CONFIG.enable_next_memo)


def is_execute_knowledge_enabled() -> bool:
    return _effective("execute_knowledge", CONFIG.enable_execute_knowledge)


def is_layered_plan_knowledge_enabled() -> bool:
    return _effective("layered_plan_knowledge", CONFIG.enable_layered_plan_knowledge)


def is_interactive_brief_enabled() -> bool:
    return _effective("interactive_brief", CONFIG.enable_interactive_brief)


def is_presentation_lookahead_enabled() -> bool:
    return _effective("presentation_lookahead", CONFIG.enable_presentation_lookahead)


def is_rich_schema_values_enabled() -> bool:
    return _effective("rich_schema_values", CONFIG.enable_rich_schema_values)


def is_orphan_resolve_enabled() -> bool:
    return _effective("orphan_resolve", CONFIG.enable_orphan_resolve)


def is_goal_aware_matching_enabled() -> bool:
    return _effective("goal_aware_matching", CONFIG.enable_goal_aware_matching)
