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

  ⭐ **優先 composite block — 看到下列關鍵字一律標 composite，不要標 primitive**:
  - user 字面寫「SPC Panel」「spc panel」「SPC 面板」 → **block_spc_panel** (composite，1-step 自處理 fetch+unnest+chart)
    use when: 「機台最後 OOC 的 SPC 狀況」「畫 xbar chart 過去 N 天」「列出 SPC charts」
  - user 字面寫「APC Panel」「apc panel」「APC 面板」 → **block_apc_panel**
    use when: 「APC 參數 etch_time 趨勢」「畫 APC 設定值變化」
  - 多 SPC long-form 分析 (不出圖只重整) → **block_spc_long_form**
  - 多 APC long-form 分析 → **block_apc_long_form**

  primitive 終端（**只有當 user 沒提到 panel/composite 時才用**）:
  - 趨勢線 → block_line_chart
  - 比較長條 → block_bar_chart
  - 箱型 → block_box_plot
  - 散布 → block_scatter_chart
  - 表格 → **block_data_view** (⚠ 不是 block_table — block_table 不存在！)
  - verdict pass/fail → block_step_check
  - 告警 → block_alert
  - Pareto 80/20 → block_pareto
  （不確定就留空字串）

  ⚠ **重要**：terminal_block 必須是上面列出的真實 block_id 之一，不要捏造。
  如果 user 字面提到某個 block name (e.g. "SPC Panel" / "Pareto" / "Cpk")，**直接抄過去**不要翻譯。

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

    # v19 (2026-05-14): chat mode (skip_confirm=True) ALSO runs clarify
    # so chat users see intent bullets like Skill Builder. Pause-handling
    # for chat: see agent_orchestrator_v2/nodes/tool_execute.py which
    # detects the intent_confirm_required SSE event, stores pending state
    # in agent_orchestrator_v2.pending_clarify, returns clarify_pending
    # tool_result, and a separate /agent/chat/intent-respond endpoint
    # resumes the build when the user confirms via BulletConfirmCard.
    #
    # (was previously: short-circuit on skip_confirm to avoid pausing the
    # chat agent's tool loop, but this hid the bullets entirely from
    # chat users — per user feedback 2026-05-14 "新的skill 就是要出現，
    # 不論是 skill builder or chat mode")

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


# v25 C: deterministic keyword → block_id mapping. When user literally
# mentions a block by name in bullet text, force terminal_block to match
# the real catalog name (bypass LLM's translation/hallucination).
# Order matters: more specific patterns first so "SPC Panel" doesn't get
# overshadowed by a generic "spc" matcher (we don't have one — but stay safe).
_KEYWORD_BLOCK_MAP: list[tuple[str, str]] = [
    # composite blocks (highest priority)
    (r"spc[\s_-]?panel|SPC[\s_-]?面板", "block_spc_panel"),
    (r"apc[\s_-]?panel|APC[\s_-]?面板", "block_apc_panel"),
    (r"spc[\s_-]?long[\s_-]?form", "block_spc_long_form"),
    (r"apc[\s_-]?long[\s_-]?form", "block_apc_long_form"),
    # explicit primitive names users might type
    (r"pareto|帕雷托|柏拉圖", "block_pareto"),
    (r"box[\s_-]?plot|箱型圖", "block_box_plot"),
    (r"scatter[\s_-]?plot|scatter[\s_-]?chart|散布圖", "block_scatter_chart"),
    (r"histogram|直方圖", "block_histogram_chart"),
    (r"xbar[\s_-]?r[\s_-]?chart|X-bar[\s_-]?R", "block_xbar_r"),
    (r"imr|I-MR", "block_imr"),
    (r"cusum|EWMA", "block_ewma_cusum"),
    (r"wafer[\s_-]?heatmap|wafer[\s_-]?map", "block_wafer_heatmap"),
    # known fictional block_id LLM tends to invent → map to real name
    (r"^block_table$", "block_data_view"),
]
_KEYWORD_BLOCK_PATTERNS = [(re.compile(p, re.IGNORECASE), b) for p, b in _KEYWORD_BLOCK_MAP]


def _coerce_terminal_block_by_keyword(text: str, current_tb: str) -> str:
    """v25 C: if bullet text contains a recognizable block keyword, force
    terminal_block to the real catalog block_id. Also fixes LLM-invented
    block names that don't exist in catalog (e.g. 'block_table'). Returns
    the coerced block_id (or current_tb when no keyword matched).
    """
    # First: keyword in bullet text wins (user's literal intent)
    for pat, real_id in _KEYWORD_BLOCK_PATTERNS:
        if pat.search(text):
            if current_tb != real_id:
                logger.info(
                    "clarify_intent: bullet text keyword '%s' → terminal_block "
                    "'%s' (was %r)",
                    pat.pattern, real_id, current_tb,
                )
            return real_id
    # Fallback: if LLM emitted a fictional block_id, map it
    for pat, real_id in _KEYWORD_BLOCK_PATTERNS:
        if pat.fullmatch(current_tb or ""):
            return real_id
    return current_tb


def _sanitize_bullets(raw: Any) -> list[dict[str, Any]]:
    """Normalize LLM bullets output into a known shape, cap to MAX_BULLETS.

    Each bullet must have an `id` and non-empty `text`. Optional fields:
    `terminal_block` (block_id hint for preview), `options` (MCQ for true
    enum disambiguation).

    v25 C: post-process terminal_block via _coerce_terminal_block_by_keyword
    so user's literal block-name mentions (e.g. "SPC Panel") always win over
    LLM's translation, and fictional block_ids get mapped to real catalog
    names.
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
        tb_raw = str(item.get("terminal_block") or "").strip()
        # v25 C: deterministic keyword override
        tb = _coerce_terminal_block_by_keyword(text, tb_raw)
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
        # v25 B reverted in v27.1: stripping `→ 預期用 X` dropped from 3/3 to
        # 1/3 spc_panel adoption — macro_plan needed the explicit signal to
        # override its default block choice. Safe to restore because v25 C
        # (_coerce_terminal_block_by_keyword) guarantees terminal_block is
        # a real catalog block_id (no more block_table hallucination).
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
