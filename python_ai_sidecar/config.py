"""Sidecar runtime configuration — loaded once at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class SidecarConfig:
    service_token: str
    port: int
    allowed_caller_ips: tuple[str, ...]

    # Phase 5a — reverse direction: sidecar → Java for every DB read/write.
    java_api_url: str
    java_internal_token: str
    java_timeout_sec: float

    # Performance feature flags (2026-06-11 / 2026-06-12).
    # Read once at startup; per-request override via `X-Feature-Flags` HTTP header
    # (see python_ai_sidecar/feature_flags.py).
    enable_prompt_cache: bool
    enable_auto_signal: bool
    # Round 1 (2026-06-12): three flags for speed/accuracy improvements.
    enable_atomic_add_connect: bool
    enable_auto_verifier: bool
    enable_strict_tool_id: bool
    # Round 2 (2026-06-12): orphan-duplicate add_node guard. Rejects when canvas
    # already has a node with the same (block_id, params) AND no downstream
    # edges — KIMI's "echo" behaviour signature. See SLASH-13 R2 trace analysis.
    enable_no_duplicate_node: bool
    # Round 3 (2026-06-12): context-aware per-sub-phase prompt assembly. Mid-phase
    # canvas snapshot gains upstream output columns + sample so construct/tune
    # rounds can fill params without blind-guessing. See
    # docs/agent-subphase-prompt-design.html.
    enable_rich_canvas_snapshot: bool
    # Round 4 (2026-06-12): inject agent_knowledge (high-priority + RAG) into the
    # v30 builder goal_plan_node. Was dead for v30 — goal_plan never read it,
    # only the legacy plan_node did. See SLASH-13 analysis.
    enable_plan_knowledge: bool
    # C2 (2026-06-12): strict plan-deliverable check in finalize_node. When the
    # plan's final phase declares a presentation kind (chart/table/scalar/alarm)
    # but the built pipeline has NO terminal block covering it, force a surfaced
    # `failed_missing_output` instead of a silent `finished`. Catches "asked for
    # chart, got no chart" false-success. Plan-level fact check, NOT a prompt rule.
    enable_strict_phase_output: bool
    # Phase-loop refine bundle (2026-06-13). Address the spc-cpk failure class
    # (intent lost across rounds, verify advancing on wrong-kind terminal, params
    # filled blind). See Todos.md "Phase Loop Refine".
    #  - construct_param_doc: inject the pending block's param doc at construct/tune.
    #  - strict_phase_verify: verifier REJECTs when no terminal covers phase.expected
    #    (fixes the "filter satisfies chart phase" bug) instead of advancing.
    #  - next_memo: mutation tools carry a required `next` plan; surfaced to the
    #    next round so multi-block intent (filter THEN chart) survives.
    enable_construct_param_doc: bool
    enable_strict_phase_verify: bool
    enable_next_memo: bool
    # V58 knowledge-layer routing (2026-06-14). agent_knowledge gained
    # applies_to ('plan'|'execute'|'both') + always_on. See spc-ooc analysis +
    # docs/agent-subphase-prompt-design.html.
    #  - execute_knowledge: phase_loop injects execute-layer RAG knowledge
    #    (applies_to ∈ {execute,both}) at the pick sub-phase, so block-choice
    #    rules (e.g. "全廠 → list_objects + foreach") reach the layer that
    #    actually picks the source block — not just the (block-agnostic) plan.
    #  - layered_plan_knowledge: goal_plan retrieves only the plan slice and
    #    shrinks the always-on dump from "all high bodies" to always_on=true
    #    core + RAG. OFF → legacy (all high, no layer filter) preserved exactly.
    enable_execute_knowledge: bool
    enable_layered_plan_knowledge: bool
    # Interactive brief (2026-06-15). Chat ALWAYS emits a collaborative design
    # brief before building: each open decision is options + 其它(free-text);
    # when the user resolves all decisions the build auto-starts. Replaces the
    # haiku "complete → skip confirm" judgment with a deterministic always-align
    # gate. See docs + the spc-cpk freeze incident discussion.
    enable_interactive_brief: bool
    # 2026-06-17: resolve each presentation phase's input contract up front and
    # inject it as the upstream handling phase's target (downstream-driven
    # handling). Cuts "vague transform → spin" detours.
    enable_presentation_lookahead: bool
    # 2026-06-17: list TRUE distinct values of low-card string columns (full
    # output, not sample) + fold just-added node schema into the post-add
    # tool_result. Removes inspect_node_output detours before filter/groupby.
    enable_rich_schema_values: bool
    # 2026-06-18: isolated-node (no in+out edge) → agent connect-or-remove round
    # before finalize, instead of silent failed_structural.
    enable_orphan_resolve: bool
    # 2026-06-18: re-rank MATCHING BLOCKS by phase-goal relevance (not kind only)
    # so adjacent same-kind phases don't show identical luring candidate lists.
    enable_goal_aware_matching: bool

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        token = os.getenv("SERVICE_TOKEN", "").strip()
        if not token:
            # Dev fallback — production MUST set SERVICE_TOKEN via env.
            token = "dev-service-token"
        java_token = os.getenv("JAVA_INTERNAL_TOKEN", "").strip() or "dev-internal-token"

        return cls(
            service_token=token,
            port=int(os.getenv("SIDECAR_PORT", "8050")),
            allowed_caller_ips=tuple(
                ip.strip() for ip in os.getenv("ALLOWED_CALLERS", "127.0.0.1,::1").split(",") if ip.strip()
            ),
            java_api_url=os.getenv("JAVA_API_URL", "http://localhost:8002").rstrip("/"),
            java_internal_token=java_token,
            java_timeout_sec=float(os.getenv("JAVA_TIMEOUT_SEC", "30")),
            enable_prompt_cache=_read_bool_env("ENABLE_PROMPT_CACHE", default=True),
            enable_auto_signal=_read_bool_env("ENABLE_AUTO_SIGNAL", default=False),
            enable_atomic_add_connect=_read_bool_env("ENABLE_ATOMIC_ADD_CONNECT", default=False),
            enable_auto_verifier=_read_bool_env("ENABLE_AUTO_VERIFIER", default=False),
            enable_strict_tool_id=_read_bool_env("ENABLE_STRICT_TOOL_ID", default=False),
            enable_no_duplicate_node=_read_bool_env("ENABLE_NO_DUPLICATE_NODE", default=False),
            enable_rich_canvas_snapshot=_read_bool_env("ENABLE_RICH_CANVAS_SNAPSHOT", default=False),
            enable_plan_knowledge=_read_bool_env("ENABLE_PLAN_KNOWLEDGE", default=False),
            enable_strict_phase_output=_read_bool_env("ENABLE_STRICT_PHASE_OUTPUT", default=False),
            enable_construct_param_doc=_read_bool_env("ENABLE_CONSTRUCT_PARAM_DOC", default=False),
            enable_strict_phase_verify=_read_bool_env("ENABLE_STRICT_PHASE_VERIFY", default=False),
            enable_next_memo=_read_bool_env("ENABLE_NEXT_MEMO", default=False),
            enable_execute_knowledge=_read_bool_env("ENABLE_EXECUTE_KNOWLEDGE", default=False),
            enable_layered_plan_knowledge=_read_bool_env("ENABLE_LAYERED_PLAN_KNOWLEDGE", default=False),
            enable_interactive_brief=_read_bool_env("ENABLE_INTERACTIVE_BRIEF", default=False),
            enable_presentation_lookahead=_read_bool_env("ENABLE_PRESENTATION_LOOKAHEAD", default=False),
            enable_rich_schema_values=_read_bool_env("ENABLE_RICH_SCHEMA_VALUES", default=False),
            enable_orphan_resolve=_read_bool_env("ENABLE_ORPHAN_RESOLVE", default=False),
            enable_goal_aware_matching=_read_bool_env("ENABLE_GOAL_AWARE_MATCHING", default=False),
        )


CONFIG = SidecarConfig.from_env()
