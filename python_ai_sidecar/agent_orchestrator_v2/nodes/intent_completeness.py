"""intent_completeness_node — graph-level gate that asks the user for missing
spec dimensions BEFORE the main LLM ever sees the prompt.

Why a graph node and not a system-prompt rule:
  Empirical (2026-05-02 chat session log): the main LLM was given an explicit
  "if presentation unspecified → call confirm_pipeline_intent" rule in the
  system prompt and ignored it, choosing search_published_skills →
  build_pipeline_live anyway. Per the operating principle "流程是 agent 的工
  作，LLM 是大腦，只做思考才對", flow control belongs in the graph; the
  system-prompt rule was demoted to advisory text only.

Decision:
  complete       — spec is fully specified across (inputs, logic, presentation)
  incomplete     — at least one of the three is missing/ambiguous → emit a
                   `design_intent_confirm` SSE card with the haiku's best
                   guess + alternatives, force_synthesis to stop the turn.

Bypass conditions (return complete without calling the LLM):
  - intent in {"vague","clarified"}      — earlier nodes handled clarification
  - intent does NOT start with "clear_"   — fallback / unknown
  - user_message contains [intent_confirmed:<id>] — user already confirmed
  - user_message contains [intent=<id>]   — clarify-card pick (other path)

NOTE on builder mode:
  We deliberately do NOT bypass for mode=="builder". Even when the user is
  staring at a Pipeline Builder canvas, "presentation 不明" is a real concern
  — without an explicit chart/table/alert hint, the sub-agent picks a default
  that may not match user intent. The classification prompt is permissive
  enough that pure modification verbs ("改成 5 天") classify as `complete`
  (the existing canvas IS the presentation), so we won't over-fire.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client

logger = logging.getLogger(__name__)


# Match either prefix anywhere near the start (e.g. after a "[Focused on ...]"
# header the panel may inject); same tolerance as intent_classifier.
_CONFIRMED_PREFIX_RE = re.compile(r"\[intent_confirmed:[a-zA-Z0-9_\-]+\]")
_INTENT_PREFIX_RE = re.compile(r"\[intent=[a-zA-Z0-9_\-]+\]")


_COMPLETENESS_SYSTEM = """You judge whether a manufacturing-engineer chat
request is fully specified enough to build a pipeline without guessing.

## STEP 0 — Is this even a pipeline-building request?
If the user is asking a **knowledge / definition / how-does-X-work question**,
they're NOT trying to build a pipeline. Output `{"complete": true}` and let
the main LLM answer in plain text.

Knowledge-question signals (any of these → return complete=true immediately):
  - 「X 是什麼」/「什麼是 X」/「X 怎麼解讀」/「X 的意思」
  - 「為什麼/為何」 about a concept (not "why is EQP-07 OOC")
  - 「如何/怎麼」 about a method (e.g.「WECO 怎麼判讀」)
  - 「what is X」/ "define X" / "explain X"
  - User mentions a rule/algorithm name ALONE without a target equipment / lot
    (e.g. "WECO R5", "Cpk", "Nelson rule", "1σ band") — they're asking about
    the concept, not running it.

If it IS a pipeline-building request, check three dimensions:
  - inputs:       did the user say WHICH equipment / lot / step / date range?
                  (any concrete reference is enough — "EQP-07", "all stations",
                  "5 days", etc.)

                  When emitting the `inputs` array in your guess, use ONLY
                  these canonical names (the downstream Glass Box's HOT
                  blocks expect exactly these keys):
                    tool_id      — 機台 (EQP-XX)
                    step         — 站點 (STEP_XXX)
                    lot_id       — 批號 (LOT-XXXX)
                    recipe_id    — 配方 (RCP-XXX)
                    apc_id       — APC 模型 (APC-XXX)
                    time_range   — 時間區間 (24h / 7d / "5 processes")
                    threshold    — 數值門檻
                    object_name  — 觀測對象 (SPC / APC / FDC / EC)

                  ⚠ DO NOT invent new names like `equipment`, `timeframe_1`,
                  `eqp_07_recent_5_processes`, etc. The Glass Box can only
                  bind canonical names to its block params; non-canonical
                  ones get the build stuck and waste turns. If the user
                  needs two time-range values (e.g. "last 1 day" + "last 5
                  processes"), declare two inputs both named `time_range`
                  is NOT allowed — instead give the second one a clear
                  semantic name like `recent_window` only AFTER all 8
                  canonical names are exhausted (rare).
  - logic:        did the user say WHAT to compute? (OOC rate, count,
                  trend, cpk, threshold check, etc.)
  - presentation: did the user say HOW to present?
                  Pick the most specific kind from the canonical list:
                    line_chart        — 折線/趨勢圖/趨勢分析 (time-series)
                    bar_chart         — 長條圖/Pareto/分組計數
                    control_chart     — 管制圖/SPC chart/UCL/LCL
                    heatmap           — 熱圖/雙維度密度
                    table             — 表格/列表/清單
                    alert             — 告警/通知/超過門檻就 fire
                    mixed_table_alert — 表格 + 告警同時呈現
                    mixed_chart_alert — 圖表 + 告警同時呈現
                  If user said NONE of these — presentation is missing.

Output JSON only (no markdown fences). Keep keys/values lowercase ASCII.

If complete (or knowledge-only):
  {"complete": true}

If incomplete (at least one of inputs/logic/presentation is missing or ambiguous):
  {
    "complete": false,
    "missing": ["presentation", ...],     // 1-3 items
    "guess": {                              // your best guess so the user
                                            // can ✅ accept without typing
      "inputs": [
        {"name": "<short_name>", "source": "user_input|event_payload|literal",
         "rationale": "<one short sentence>"}
      ],
      "logic": "<one-sentence plain language description>",
      "presentation": "line_chart|bar_chart|control_chart|heatmap|table|alert|mixed_table_alert|mixed_chart_alert",
      "alternatives": [
        {"summary": "<another way to interpret, ≤30 chars>"}
      ]
    }
  }

Rules:
  - presentation is the dimension users skip most often — be strict here
  - inputs missing: only flag if user said NO concrete identifier at all
  - logic missing: only flag if user used vague verbs alone (analyze, look,
    check, etc.) without saying what
  - 0-2 alternatives is fine; pick contrasting interpretations
  - Output JSON only. No prose. No code fences."""


_FORCE_SYNTH_REPLY = (
    "我先跟你確認要建什麼 ↑\n"
    "點 ✅ 開始建、✏️ 想修改、❌ 取消。"
)


# Canonical input names — must match the keys Glass Box's HOT blocks accept
# so the build doesn't hunt for a non-existent param. Mapping on the right
# is keyed by lowercase user-supplied name (after stripping leading $) and
# returns the canonical key. Anything not matched falls back to the raw
# (sanitized) name.
_CANONICAL_INPUTS: set[str] = {
    "tool_id", "step", "lot_id", "recipe_id", "apc_id",
    "time_range", "threshold", "object_name",
}
_INPUT_NAME_ALIASES: dict[str, str] = {
    # equipment / tool
    "equipment":     "tool_id",
    "equipment_id":  "tool_id",
    "machine":       "tool_id",
    "machine_id":    "tool_id",
    "eqp":           "tool_id",
    "eqp_id":        "tool_id",
    "tool":          "tool_id",
    # step
    "step_id":       "step",
    "station":       "step",
    "station_id":    "step",
    # lot
    "lot":           "lot_id",
    "batch":         "lot_id",
    "batch_id":      "lot_id",
    # recipe
    "recipe":        "recipe_id",
    "recipe_version":"recipe_id",
    # APC
    "apc":           "apc_id",
    # time
    "timeframe":     "time_range",
    "timeframe_1":   "time_range",
    "timeframe_2":   "time_range",
    "time_window":   "time_range",
    "duration":      "time_range",
    "period":        "time_range",
    # object
    "subsystem":     "object_name",
    "object":        "object_name",
}

# Allowed presentation kinds — must match the 8-way enum surfaced to the
# DesignIntentCard radio. Old values (alert/chart/table/scalar/mixed) get
# remapped to the closest new kind for back-compat with cached intents.
_CANONICAL_PRESENTATION: set[str] = {
    "line_chart", "bar_chart", "control_chart", "heatmap",
    "table", "alert", "mixed_table_alert", "mixed_chart_alert",
}
_PRESENTATION_ALIASES: dict[str, str] = {
    "chart":      "line_chart",     # ambiguous "chart" defaults to line
    "scalar":     "table",          # single-number → small table
    "mixed":      "mixed_chart_alert",
    "histogram":  "bar_chart",
    "pareto":     "bar_chart",
    "spc":        "control_chart",
    "spc_chart":  "control_chart",
    "trend":      "line_chart",
}


def _normalize_input(raw: dict) -> dict:
    """Force a canonical input name. Falls back to the raw name when no
    sensible mapping exists (rare — caller should still be able to use
    those, just with worse Glass Box matching).
    """
    if not isinstance(raw, dict):
        return raw
    name_in = (raw.get("name") or "").strip().lstrip("$").lower()
    if not name_in:
        return raw
    if name_in in _CANONICAL_INPUTS:
        canonical = name_in
    elif name_in in _INPUT_NAME_ALIASES:
        canonical = _INPUT_NAME_ALIASES[name_in]
    else:
        # Last-mile heuristic: substring match against canonical keys.
        canonical = next(
            (c for c in _CANONICAL_INPUTS if c in name_in or name_in in c),
            name_in,
        )
    out = dict(raw)
    out["name"] = canonical
    return out


def _normalize_presentation(raw: str | None) -> str:
    """Map LLM's presentation string to the canonical 8-way enum."""
    if not raw:
        return "mixed_chart_alert"
    val = raw.strip().lower()
    if val in _CANONICAL_PRESENTATION:
        return val
    if val in _PRESENTATION_ALIASES:
        return _PRESENTATION_ALIASES[val]
    # Unknown → safe default that shows both data + warning if any
    return "mixed_chart_alert"


def _has_bypass_prefix(msg: str) -> bool:
    return bool(_CONFIRMED_PREFIX_RE.search(msg) or _INTENT_PREFIX_RE.search(msg))


def _parse_decision(text: str) -> Dict[str, Any] | None:
    text = text.strip()
    # Tolerate models that wrap JSON in code fences despite the instruction.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


async def intent_completeness_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    user_message = state.get("user_message") or ""
    mode = state.get("mode") or "chat"
    intent = (state.get("intent") or "").lower()

    # ── Bypass conditions (return without calling the LLM) ─────────
    # We intentionally do NOT bypass for mode=="builder" — see module docstring.
    # Pure-modification prompts ("改成 5 天") classify as complete; ambiguous
    # ones ("分析 EQP-07 OOC") still deserve a confirm card on canvas too.
    if intent in ("vague", "clarified"):
        logger.info("intent_completeness: bypass (intent=%s already routed)", intent)
        return {}
    if not intent.startswith("clear_"):
        # Unknown / fallback intent — let llm_call handle it; don't gate.
        logger.info("intent_completeness: bypass (intent=%r not gateable)", intent)
        return {}
    if _has_bypass_prefix(user_message):
        logger.info("intent_completeness: bypass via [intent_*] prefix")
        return {}

    # ── Completeness classification (one haiku-class call) ────────
    client = get_llm_client()
    try:
        resp = await client.create(
            system=_COMPLETENESS_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=600,
        )
        decision = _parse_decision(resp.text or "")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "intent_completeness: classification failed (%s) — pass-through to llm_call",
            e,
        )
        return {}

    if not decision:
        logger.warning("intent_completeness: unparseable decision — pass-through")
        return {}

    if decision.get("complete") is True:
        logger.info("intent_completeness.decision complete=True intent=%s", intent)
        return {}

    # ── Incomplete: emit design_intent_confirm + force synthesis ──
    guess = decision.get("guess") or {}
    missing = decision.get("missing") or []

    card_id = f"intent-{uuid.uuid4().hex[:8]}"
    # Normalize input names to canonical keys before sending the card to
    # the user. Even with the prompt rule, LLMs occasionally invent names
    # like $equipment or $timeframe_1 — Glass Box's HOT blocks can't bind
    # those, so the build gets stuck. This deterministic post-process
    # ensures whatever lands in the spec is something the builder can use.
    normalized_inputs = [_normalize_input(i) for i in (guess.get("inputs") or [])]
    spec_payload = {
        "card_id": card_id,
        "inputs": normalized_inputs,
        "logic": guess.get("logic") or "",
        "presentation": _normalize_presentation(guess.get("presentation")),
        "alternatives": guess.get("alternatives") or [],
    }

    logger.info(
        "intent_completeness.decision complete=False missing=%s card_id=%s "
        "guess_presentation=%s",
        missing, card_id, spec_payload["presentation"],
    )

    pb_emit = (config.get("configurable", {}) or {}).get("pb_event_emit") if config else None
    if pb_emit is not None:
        try:
            pb_emit({"type": "design_intent_confirm", **spec_payload})
        except Exception as ee:  # noqa: BLE001
            logger.warning("intent_completeness: pb_emit failed: %s", ee)

    # Synthetic AIMessage so synthesis just renders this without another LLM call.
    return {
        "force_synthesis": True,
        "messages": [AIMessage(content=_FORCE_SYNTH_REPLY)],
    }
