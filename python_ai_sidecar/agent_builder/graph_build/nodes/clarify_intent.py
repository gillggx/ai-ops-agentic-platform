"""clarify_intent_node — G1 pre-plan clarification gate (v15, 2026-05-13).

Catches high-ambiguity terms in the user instruction BEFORE plan_node
burns Opus tokens guessing. Emits 0-3 multiple-choice questions; user's
answers come back via /agent/build/clarify-respond and get woven into
state.instruction so plan_node sees a disambiguated prompt.

Why Haiku not Opus: this is a classification task ("which buckets does
this prompt fall into?"), not a generation task. Cheap and fast.

Trigger types we look for:
  - display verb ambiguity: "顯示/看/展示/列出" → snapshot table vs trend chart
  - time scope missing: "最近/最後/過去" without N → 24h vs 7d vs 30d
  - subject ambiguity: "機台/批次" without ID → declare $input vs literal
  - comparison target unclear: "比較" without explicit pairs
  - severity threshold unclear: ">2" vs ">=2" vs ">1.5σ"

If the prompt is already precise (rare on real user input), emit
proceed_directly=true and bypass the gate.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from langgraph.types import interrupt

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client


logger = logging.getLogger(__name__)


_SYSTEM = """你是 builder 前置的「意圖釐清器」(v18, 2026-05-14)。

你的工作 = 把 user 的 instruction **重述成 2-6 個 intent bullets**，每個 bullet
代表 user 需求的一個關鍵點（對象 / 觸發 / 條件 / 動作 / 顯示形式）。
然後 user 會逐 bullet 確認 ✓ ✗ 或改寫。**你不負責 build pipeline。**

== 為什麼用 bullets 而不是 MCQ ==
LLM 用 MCQ 問「snapshot 還是 trend?」user 看不到模型怎麼理解他的話。
改成「我聽到的是：① X ② Y ③ Z」，user 直接看出哪裡懂錯，效率高十倍。

== Bullet 寫法 ==
每個 bullet 一句話，包含：
  - 主詞（誰 / 哪台機台 / 哪個 SPC）
  - 動作（看 / 計算 / 比較 / 觸發）
  - 條件（時間範圍 / 閾值 / 過濾）
  - 顯示形式（chart / table / verdict / alarm）

== 標 terminal_block hint ==
若 bullet 描述「顯示 / 觸發 / 輸出」型動作，標出對應 block_id：
  - 趨勢線 → block_line_chart
  - 比較長條 → block_bar_chart
  - 箱型 → block_box_plot
  - 散布 → block_scatter_plot
  - 表格 → block_table
  - verdict pass/fail → block_step_check
  - 告警 → block_alert
  （不確定就留空字串）

== 何時用 MCQ options ==
只有當某 bullet 真的有 enum 歧義（例：「最近」是 24h vs 7d vs 30d）才掛 options，
其它 bullet 不需要 options，user 直接 ✓✗ 即可。

== 何時直接 proceed ==
若 instruction 完全只有一句寒暄、無工作意圖（例 "111", "你好", "test"）→
回 `{"refuse_low_signal": true, "reason": "..."}` — 不要硬擠 bullets。

== 何時 proceed_directly ==
若 instruction 已超精確（例：給了完整 pipeline JSON 樣本）→
回 `{"proceed_directly": true, "bullets": []}`

== 二次釐清模式 (too_vague_reason 有值) ==
若 user_msg 帶有「PREVIOUS MACRO_PLAN FAILED:」段落，那是上次 macro_plan
判定 too_vague 的原因。針對該原因產出更具體的 bullets，幫 user 看出衝突點，
解掉它後我們再重試 macro_plan。

== 輸出 schema ==
僅輸出 JSON，無 markdown fence：

{
  "bullets": [
    {
      "id": "b1",
      "text": "對象：所有機台（你想限定特定 ID 嗎？）",
      "terminal_block": "",
      "options": [
        {"value": "all_machines", "label": "掃所有機台"},
        {"value": "specific_id", "label": "只看某台（要 user 給 ID）"}
      ]
    },
    {
      "id": "b2",
      "text": "顯示這些 OOC SPC 的 trend chart",
      "terminal_block": "block_line_chart"
    },
    {
      "id": "b3",
      "text": "OOC chart 數量 > 2 觸發 alarm",
      "terminal_block": "block_step_check"
    }
  ],
  "plan_summary": "(一句話總結 user 要做什麼)"
}

低 signal 拒絕：
{"refuse_low_signal": true, "reason": "instruction 只有 '111'，無工作意圖"}

絕對不要：
- 不要超過 6 個 bullets（拆 build）
- 不要把 bullet 寫成「你想要 X 嗎？」這種疑問句 — 寫成陳述句 user 才好 ✓✗
- 不要在 bullet 裡夾 JSON / 程式碼 — 純自然語言
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def clarify_intent_node(state: BuildGraphState) -> dict[str, Any]:
    # Skip if already passed once (resume after user picks answers comes
    # back here, but with clarify_attempts=1; only fire LLM call when 0).
    # v18: macro_plan resets clarify_attempts to 0 when looping back via
    # needs_clarify, so we get a fresh chance to ask targeted questions.
    attempts = state.get("clarify_attempts", 0)
    if attempts >= 1:
        logger.info("clarify_intent: skipped (already done, attempts=%d)", attempts)
        return {}

    # Chat mode (skip_confirm=True) has no UI to surface clarification
    # questions — the chat orchestrator already asked the user before
    # calling build_pipeline_live, and there is no /agent/build/clarify-
    # respond path from the chat panel. If we interrupt() here the graph
    # pauses forever and the user sees an empty canvas. Skip the gate;
    # macro_plan will handle whatever residual ambiguity remains by
    # picking sensible defaults from block descriptions.
    if state.get("skip_confirm"):
        logger.info("clarify_intent: skipped (skip_confirm=True, chat mode)")
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "skip_confirm"})],
        }

    instruction = state.get("instruction") or ""
    if not instruction.strip():
        return {"clarify_attempts": 1, "clarifications": {}}

    from python_ai_sidecar.agent_builder.graph_build.trace import get_current_tracer
    tracer = get_current_tracer()

    client = get_llm_client()

    # v18: when looping back from macro_plan(too_vague), feed the reason
    # into the prompt so clarify asks targeted questions about the actual
    # ambiguity (not generic ones it already failed on).
    too_vague_reason = state.get("too_vague_reason") or ""
    too_vague_attempts = int(state.get("too_vague_attempts") or 0)
    extra_context = ""
    if too_vague_reason:
        extra_context = (
            f"\n\nPREVIOUS MACRO_PLAN FAILED (attempt {too_vague_attempts}):\n"
            f"{too_vague_reason[:1500]}\n\n"
            "請出 bullets 直接幫 user 解掉上述衝突 — 不要重複問 user 已經回答過的事。"
        )
    user_msg = f"USER INSTRUCTION:\n{instruction[:1500]}{extra_context}"

    decision: dict[str, Any] = {"bullets": []}
    raw_text = ""
    try:
        # Spec said "use Haiku" but BaseLLMClient.create doesn't accept a
        # per-call model override. Using default model — this is a small
        # JSON-output classification call (~1k system + 500 user), cost
        # is negligible compared to plan_node's ~60k catalog payload.
        resp = await client.create(
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=2048,
        )
        raw_text = resp.text or ""
        text = _strip_fence(raw_text)
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
                _extract_first_json_object,
            )
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("clarify_intent: LLM/parse failed (%s) — proceeding without clarification", ex)
        if tracer is not None:
            tracer.record_llm(
                "clarify_intent_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=None, error=str(ex)[:300],
            )
            tracer.record_step("clarify_intent_node", status="failed", error=str(ex)[:300])
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": str(ex)[:200]})],
        }

    # Record the successful LLM call regardless of decision branch below.
    if tracer is not None:
        tracer.record_llm(
            "clarify_intent_node", system=_SYSTEM, user_msg=user_msg,
            raw_response=raw_text, parsed=decision, resp=resp,
        )

    # Refuse path — model decided instruction has zero work-intent (e.g. "111").
    if isinstance(decision, dict) and decision.get("refuse_low_signal"):
        reason = str(decision.get("reason") or "instruction lacks any actionable intent")
        logger.info("clarify_intent: refused low signal — %s", reason[:120])
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="refused",
                verdict="refuse_low_signal", reason=reason[:300],
            )
        return {
            "clarify_attempts": 1,
            "status": "refused",
            "summary": f"看不出工作意圖：{reason[:200]}。請更具體描述你想做什麼。",
            "sse_events": [_event("clarify_refused", {"reason": reason[:300]})],
        }

    bullets_raw = decision.get("bullets") if isinstance(decision, dict) else None
    proceed = bool(decision.get("proceed_directly")) if isinstance(decision, dict) else False

    if proceed:
        logger.info("clarify_intent: proceed_directly — skipping bullets")
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="ok",
                verdict="proceed_directly", n_bullets=0,
            )
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "proceed_directly"})],
        }

    # Sanitize bullets and attach previews from block catalog.
    bullets = _sanitize_bullets(bullets_raw)
    bullets = await _attach_block_previews(bullets)

    if not bullets:
        # Fall through gracefully — let macro_plan try its luck.
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="ok",
                verdict="no_valid_bullets", n_bullets=0,
            )
        return {
            "clarify_attempts": 1,
            "clarifications": {},
            "sse_events": [_event("clarify_skipped", {"reason": "no valid bullets"})],
        }

    logger.info(
        "clarify_intent: emitting %d intent bullet(s)%s",
        len(bullets),
        f" (too_vague retry, attempts={too_vague_attempts})" if too_vague_reason else "",
    )

    if tracer is not None:
        tracer.record_step(
            "clarify_intent_node", status="awaiting_user",
            verdict="intent_confirm_required",
            n_bullets=len(bullets),
            bullets=bullets,
            too_vague_attempts=too_vague_attempts,
        )

    # Pause graph and wait for user confirmations via /agent/build/clarify-respond.
    user_response = interrupt({
        "kind": "intent_confirm_required",
        "session_id": state.get("session_id"),
        "bullets": bullets,
        "too_vague_reason": too_vague_reason or None,
    })

    # When resumed, user_response can be:
    #   (legacy MCQ) {"answers": {qid: value}}
    #   (new bullets) {"confirmations": {bid: {action, edit_text?}}}
    confirmations: dict[str, dict] = {}
    answers_legacy: dict[str, str] = {}
    if isinstance(user_response, dict):
        raw_conf = user_response.get("confirmations") or {}
        for bid, decision_obj in raw_conf.items():
            if isinstance(bid, str) and isinstance(decision_obj, dict):
                action = str(decision_obj.get("action") or "ok")
                edit_text = str(decision_obj.get("edit_text") or "")
                confirmations[bid] = {"action": action, "edit_text": edit_text}
        # legacy compat: treat answers as ✓ confirmations of MCQ default
        legacy_raw = user_response.get("answers") or {}
        for qid, val in legacy_raw.items():
            if isinstance(qid, str) and isinstance(val, (str, int, float, bool)):
                answers_legacy[qid] = str(val)

    # Refuse if user rejected any bullet without offering an edit.
    rejected_unedited = [
        bid for bid, d in confirmations.items()
        if d.get("action") == "reject" and not d.get("edit_text")
    ]
    if rejected_unedited:
        logger.info("clarify_intent: user rejected %d bullet(s) → refused", len(rejected_unedited))
        if tracer is not None:
            tracer.record_step(
                "clarify_intent_node", status="refused",
                verdict="user_rejected", rejected=rejected_unedited,
            )
        return {
            "clarify_attempts": 1,
            "intent_bullets": bullets,
            "intent_confirmations": confirmations,
            "status": "refused",
            "summary": f"User 拒絕 {len(rejected_unedited)} 個 intent bullets — 請重新描述需求。",
            "sse_events": [_event("clarify_refused", {"rejected": rejected_unedited})],
        }

    # Augment the instruction with confirmed/edited bullets so macro_plan
    # sees the grounded intent.
    aug_instruction = _augment_with_bullets(instruction, bullets, confirmations, answers_legacy)
    logger.info("clarify_intent: applied bullets+confirmations; instruction extended")

    if tracer is not None:
        tracer.record_step(
            "clarify_intent_node", status="resumed",
            verdict="bullets_confirmed",
            n_confirmations=len(confirmations),
            n_bullets=len(bullets),
            confirmations=confirmations,
        )

    return {
        "instruction": aug_instruction,
        "intent_bullets": bullets,
        "intent_confirmations": confirmations,
        "clarifications": answers_legacy,
        "clarify_attempts": 1,
        "sse_events": [_event("intent_confirmed", {
            "n_bullets": len(bullets),
            "n_confirmations": len(confirmations),
        })],
    }


def _sanitize_bullets(raw: Any) -> list[dict[str, Any]]:
    """Normalize LLM bullets output into a known shape, cap to MAX_BULLETS.

    Each bullet must have an `id` and non-empty `text`. Optional fields:
    `terminal_block` (block_id hint for preview), `options` (MCQ for true
    enum disambiguation).
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw[:_MAX_BULLETS], 1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        bid = str(item.get("id") or f"b{i}").strip() or f"b{i}"
        bullet: dict[str, Any] = {"id": bid, "text": text}
        tb = str(item.get("terminal_block") or "").strip()
        if tb:
            bullet["terminal_block"] = tb
        # MCQ options (optional — only when bullet has true enum ambiguity)
        opts = item.get("options")
        if isinstance(opts, list):
            clean_opts = [
                {"value": str(o["value"]), "label": str(o.get("label") or o["value"])}
                for o in opts
                if isinstance(o, dict) and isinstance(o.get("value"), str)
            ]
            if clean_opts:
                bullet["options"] = clean_opts[:6]
        out.append(bullet)
    return out


_MAX_BULLETS = 6


async def _attach_block_previews(bullets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each bullet that has terminal_block, look up block.examples[0]
    in the catalog and attach a preview chart_spec the frontend can render.

    Falls back silently when block has no examples or catalog load fails —
    bullets without preview are still useful as text-only.
    """
    if not bullets:
        return bullets
    needed = {b["terminal_block"] for b in bullets if b.get("terminal_block")}
    if not needed:
        return bullets
    try:
        from python_ai_sidecar.pipeline_builder.seedless_registry import (
            SeedlessBlockRegistry,
        )
        registry = SeedlessBlockRegistry()
        registry.load()
        # catalog keys are (name, version); pick latest version per name
        block_examples: dict[str, Any] = {}
        for (name, _v), spec in registry.catalog.items():
            if name not in needed:
                continue
            examples = spec.get("examples") or []
            if isinstance(examples, list) and examples:
                first = examples[0]
                # examples can be {description, chart_spec}, raw dict, or
                # plain pipeline-snippet shape — pick the first chart_spec
                # we find or pass through whatever the catalog stores.
                if isinstance(first, dict):
                    chart = first.get("chart_spec") or first.get("snapshot") or first
                    block_examples[name] = chart
    except Exception as ex:  # noqa: BLE001
        logger.warning("clarify_intent: block preview lookup failed: %s", ex)
        return bullets

    for b in bullets:
        tb = b.get("terminal_block")
        if tb and tb in block_examples:
            b["preview_chart_spec"] = block_examples[tb]
    return bullets


def _augment_with_bullets(
    original: str,
    bullets: list[dict[str, Any]],
    confirmations: dict[str, dict[str, Any]],
    answers_legacy: dict[str, str],
) -> str:
    """Build instruction sent to macro_plan: original + a CONFIRMED INTENT
    section listing each ✓ed (or edited) bullet so macro_plan treats them
    as ground truth and stops self-doubting.
    """
    lines: list[str] = [original.strip(), "", "── User 已確認的 intent (請以此為準, 不要再 too_vague) ──"]
    for b in bullets:
        bid = b["id"]
        text = b["text"]
        conf = confirmations.get(bid) or {}
        action = conf.get("action") or "ok"  # default = confirmed
        if action == "reject":
            continue  # rejected bullets shouldn't bleed into instruction
        if action == "edit" and conf.get("edit_text"):
            text = f"{text}  (user 改寫: {conf['edit_text']})"
        tb = b.get("terminal_block")
        suffix = f"  → 預期用 {tb}" if tb else ""
        lines.append(f"  - {text}{suffix}")
    if answers_legacy:
        lines.append("")
        lines.append("── Legacy MCQ answers ──")
        for qid, val in answers_legacy.items():
            lines.append(f"  - [{qid}] = {val}")
    return "\n".join(lines)


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
