"""pre_clarify_check_node — deterministic builder-mode clarification gate.

2026-05-11: when the user's prompt has ambiguity dimensions AND there's no
[intent_confirmed:] prefix, this node short-circuits the LLM and emits the
design_intent_confirm SSE card directly. Without this, the LLM sometimes
chose to ask via plain-text synthesis (「需要澄清: ...」), bypassing our
multi-choice card UX entirely.

Per CLAUDE.md「flow 由 graph 決定，不是 prompt rule」: we don't tell the
LLM "use confirm_pipeline_intent not text" in the prompt — we intercept
before the LLM ever sees the message.

Detector reuses the existing dimensional_clarifier (same as the intercept
inside tool_execute build_pipeline_live).

Skip cases (LLM proceeds normally):
- mode != "builder"
- user_message already starts with "[intent_confirmed:" (follow-up turn)
- detector returns 0 dimensions
- Java unreachable / clarifier crashed (best-effort, don't block)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


async def pre_clarify_check_node(
    state: Dict[str, Any], config: RunnableConfig,
) -> Dict[str, Any]:
    """Detect ambiguity dims pre-LLM. If any fire, emit card SSE +
    force_synthesis so the graph routes to synthesis without invoking
    the LLM. State key `clarify_card_emitted=True` is set so synthesis
    knows to render a minimal "waiting for user picks" message rather
    than a normal AI response.
    """
    if state.get("mode") != "builder":
        return {}
    user_msg = state.get("user_message") or ""
    if user_msg.startswith("[intent_confirmed:"):
        return {}
    snap = state.get("pipeline_snapshot") or {}

    try:
        from python_ai_sidecar.agent_orchestrator_v2.dimensional_clarifier import (
            build_clarifications,
        )
        clarifications = await build_clarifications(
            user_msg=user_msg,
            declared_inputs=snap.get("inputs") if isinstance(snap, dict) else None,
            pipeline_snapshot=snap if isinstance(snap, dict) else None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("pre_clarify_check: clarifier failed (%s) — pass through to LLM", e)
        return {}

    if not clarifications:
        return {}

    # Emit the SSE event directly via the pb_event_emit injected from
    # router agent.py (same mechanism tool_execute uses).
    event_emit = config["configurable"].get("pb_event_emit")
    card_id = f"intent-{uuid.uuid4().hex[:8]}"
    payload = {
        "type": "design_intent_confirm",
        "card_id": card_id,
        "inputs": [],
        "logic": user_msg[:200],
        "presentation": "mixed_chart_alert",
        "alternatives": [],
        "clarifications": clarifications,
    }
    if event_emit is not None:
        try:
            event_emit(payload)
        except Exception:  # noqa: BLE001
            pass

    logger.info(
        "pre_clarify_check: short-circuit LLM (%d dims) — card=%s",
        len(clarifications), card_id,
    )

    # Pre-canned synthesis text so the user sees something explainable on
    # top of the card itself (the card carries the actual choices).
    pre_synth_text = (
        f"我需要先確認 {len(clarifications)} 件事再開始建。"
        "請從上方卡片裡選擇後送出，我會立刻動工。"
    )

    return {
        "force_synthesis": True,
        "clarify_card_emitted": True,
        "synthesis_text_override": pre_synth_text,
    }
