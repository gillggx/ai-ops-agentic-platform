"""macro_plan_node — v16 (2026-05-14) Phase 1 of the macro+chunk architecture.

Replaces the 1-shot plan_node. Instead of asking the LLM to produce 21
ops + structured outputs + node_contracts in a single call (which scaled
poorly past ~8 nodes — validator caught errors, repair looped, finalize
eventually plan_unfixable), this node produces a small natural-language
"macro plan" with 5-10 steps.

Per CLAUDE.md description-driven principle: this node reads the full block
catalog ONLY to format candidate brief lines (block_id + 1-line desc) —
LLM doesn't need full param schemas here. Choosing exact block params
is deferred to compile_chunk_node, which sees the upstream context for
each individual chunk.

Output shape:
  {"plan_summary": "<sentence>",
   "macro_plan": [
     {"step_idx": 1, "text": "撈 EQP-01 過去 7d Process History",
      "expected_kind": "transform",
      "expected_cols": [],
      "candidate_block": "block_process_history"},
     {"step_idx": 2, "text": "過濾 spc_status=='OOC'",
      "expected_kind": "transform",
      "candidate_block": "block_filter"},
     ...
     {"step_idx": 7, "text": "列出 OOC charts snapshot table",
      "expected_kind": "table",
      "expected_cols": ["name","value","ucl","lcl"],
      "candidate_block": "block_data_view"}
   ]
  }

Validator runs on this minimal macro shape (no ops yet). compile_chunk_node
then walks each step.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from python_ai_sidecar.agent_builder.graph_build.state import BuildGraphState
from python_ai_sidecar.agent_helpers_native.llm_client import get_llm_client
from python_ai_sidecar.pipeline_builder.canonical_inputs import lookup as _canonical_lookup
from python_ai_sidecar.pipeline_builder.trigger_schemas import format_for_prompt as _format_trigger


logger = logging.getLogger(__name__)


# Max macro steps a build can have. Above this means the build is too
# complex to attempt in one pass — surface back to user to break into
# smaller skills.
MAX_MACRO_STEPS = 12

# v18: reject-and-ask loop — how many times macro_plan can return
# too_vague before we hard-refuse the build with a friendly message.
# 1 = "ask once"; 2 = "ask once, retry, then refuse" (current).
MAX_TOO_VAGUE_ATTEMPTS = 2


_SYSTEM = """你是 pipeline architect。User 給你需求，你把它**拆成 3-8 個高階步驟**，每步驟用一句中文描述要做什麼。

不要寫 JSON ops / 不要選 block 細項 / 不要寫 params — 那是下一個 worker 的工作。

你只要決定:
  1. 每個 step 做什麼資料動作 (依資料形狀決定：撈/解 nested/過濾/排序/聚合/視覺化/判定)
  2. 每個 step 預期輸出的「形狀」(transform/table/chart/scalar)
  3. 終端 step (table/chart/scalar) 的預期欄位 (若 user 有明說)
  4. 大概用哪個 block — **只是建議候選**，從下方候選 blocks 清單挑
  5. **每個 step 的 depends_on** — 這個 step 接在哪些上游 step 之後（用 step_idx 列表）

==選 block 的根本原則==
**你只能讀候選 blocks 清單裡每個 block 的「What」+「Output」brief 來判斷**。如果某 block 的
Output 說它回的是 nested 結構（list / dict），下游就必須先有解 nested 的步驟才能接後續轉換。
**不要憑想像 / 訓練資料中的常識**填寫 step text 或 candidate_block — 一切看下方 brief。

== 規則 ==
  - 起點是 source block (從清單裡 category=source 的挑)，source step 的 depends_on=[] (空 list)
  - 終點必須是 user 要看的形狀（chart / table / scalar）— 看 user 需求字面要求什麼
  - 中間 step 只放 user 真的需要的轉換；別加 user 沒提的聚合 / 排序 / 篩欄
  - 1-8 步皆可：**優先用 composite block 走 1 step**；只在必要時拆多步

== 🌳 DAG / depends_on 規則 (v20，強制) ==
  - **每個 step 必須帶 depends_on 欄位** (list[int])，列出這 step 直接依賴哪些上游 step 的輸出
  - source step (撈資料) → depends_on=[]
  - 線性 step (filter/sort/unnest 接前一 step) → depends_on=[前一 step_idx]
  - **平行 branch (重要！)**: 當 user 同時要求多種輸出 (e.g. 「verdict + chart」、「table + alarm」、「兩種圖」)，
    這幾個 terminal **不要串成一條**，要從同一個共用上游 fan-out:
      step 1 process_history (depends_on=[])
      step 2 unnest spc_charts (depends_on=[1])
      step 3 filter is_ooc (depends_on=[2])
      step 4 verdict step_check (depends_on=[3])    ← branch A
      step 5 spc_panel chart    (depends_on=[1])    ← branch B 從 source 重新 fan-out
  - **rules**:
      a. depends_on 的元素**必須 < 自己的 step_idx** (不可前向引用)
      b. depends_on 的元素**必須是已經出現過的 step_idx** (不可指向不存在 step)
      c. **不可有 cycle** (因為 a 規則自然防止)
      d. **多 terminal 同時要產出時 (chart + verdict / table + chart) — 各 terminal 自己 fan-out 自己的分支**，
         不要把 chart 接在 verdict 後面 (verdict 是 bool/scalar，沒有 dataframe 給 chart 用)
      e. **沒有 parallel branch 上限** — 你判斷 user 需要幾個 terminal 就開幾個 branch

== 🔗 跨 branch 取值 → 一律用 block_join (v23, 重要！) ==
  當 step N 需要「另一 branch 的 runtime 輸出值」時 (e.g.「篩到 last X 的時間」、「過濾到 max value 的記錄」、
  「比對某 group 的 count 結果」)，**禁止**用 block_filter+literal value，**必須**用 block_join：
    - block_join 的 depends_on=[左表, 右表] (兩個 branch 各自的 terminal)
    - inner join 預設只保留 join key 相符的 rows，自動達到「篩到 last X」的效果
  ❌ 錯誤：step 7 [block_filter] deps=[3], text="篩到 last OOC time"
       → LLM 找不到 last OOC time 的 literal，會幻覺出垃圾 value (例如 "EQP-01")
       → 0 row → 下游 chart/table 全空
  ✅ 正確：step 7 [block_join] deps=[3, 5], text="把 step 3 的 OOC 全表 join step 5 的 last OOC time"
       → join by eventTime → 自動只剩 last OOC time 的 rows

⚠ 每個 step 必須是「**單一原子動作**」 — 不要把多動作塞同一 step：
  - ❌ 「撈 process_history 並解開 spc_charts 並篩 xbar」(三件事擠一句)
  - ✅ step_1: 撈 process_history → step_2: 解開 spc_charts → step_3: 篩 xbar
  - ❌ 「撈資料 + 計算 mean + 畫線」 → 三個 steps
  - ✅ 看到「並 / 加上 / 同時 / + / 然後」這種連接詞，**拆**

理由：每 step 編譯成 1 add_node，下一個 step 編譯時才看得到上一個 step 的實際輸出欄位
驗證 column ref。同 step 塞多動作 → 後面動作的 col 沒人驗 → runtime 才爆。

⭐ **composite block 例外（重要！）**:
  如果候選 blocks 裡有 **composite / panel block** —— 該 block 的 What/Output brief 自稱
  「自給自足」「1-block 全包」「source-mode」「不需上游」「one block, right semantics」
  —— 那它的設計就是**「1 個 block = 整條 pipeline」**。
  此時 macro_plan 應該只給 **1 個 step**，整條 pipeline 就是該 composite block 自己。
  composite 自己處理 fetch+unnest+filter+render，**你拆多步反而會踩它的雷**（已知 case 砍剩 1 row）。

== Few-shot 範例 ==

範例 1: User 說「看 EQP-01 STEP_001 xbar_chart 過去 7 天」
✅ 正確（block_spc_panel 是 parameterized composite — step + chart_name 必填，內部 fetch，1 step 即可）:
{
  "plan_summary": "用 block_spc_panel 一個 node 撈 EQP-01 STEP_001 xbar_chart 過去 7 天並出圖",
  "macro_plan": [
    {"step_idx": 1, "text": "畫 EQP-01 STEP_001 xbar_chart 過去 7 天 line chart (composite)",
     "expected_kind": "chart", "expected_cols": ["eventTime", "value", "ucl", "lcl"],
     "candidate_block": "block_spc_panel", "depends_on": []}
  ]
}
（compile_chunk 會填 params: step='STEP_001', chart_name='xbar_chart', tool_id='EQP-01', time_range='7d'）
❌ 錯誤（4 step composition — 已知會把多 SPC 砍剩 1 點）:
  process_history → unnest → filter → line_chart
❌ 錯誤（把 spc_panel 串在 process_history 後面）:
  process_history → spc_panel — composite 已含 fetch，再串 upstream 就是浪費 + 高機率搞砸 step+chart_name

範例 2: User 說「看 EQP-01 過去 24 小時 APC temperature 趨勢」
✅ 同樣 1 step（block_apc_panel — step + chart_name 必填）:
{
  "plan_summary": "用 block_apc_panel 一個 node 畫 EQP-01 24h temperature trend",
  "macro_plan": [
    {"step_idx": 1, "text": "畫 EQP-01 APC temperature 過去 24h trend (composite)",
     "expected_kind": "chart", "expected_cols": ["eventTime", "value"],
     "candidate_block": "block_apc_panel", "depends_on": []}
  ]
}
（compile_chunk 會填 params: step='STEP_001' (或 user 提到的 step), chart_name='temperature',
  tool_id='EQP-01', time_range='24h'。⚠ user 沒提 step 時，**問 user 確認 step**，不要瞎猜）

範例 3: User 說「機台最後一次 OOC 時的 SPC 狀況 + 觸發 alarm (>= 2 OOC)」(skill mode)
✅ DAG 寫法（verdict 分支 + chart 分支從共用上游 fan-out，不串成一條）:
{
  "plan_summary": "verdict branch + spc_panel chart, both fan out from process_history",
  "macro_plan": [
    {"step_idx": 1, "text": "撈 process_history nested", "candidate_block": "block_process_history",
     "expected_kind": "transform", "depends_on": []},
    {"step_idx": 2, "text": "展開 spc_charts", "candidate_block": "block_unnest",
     "expected_kind": "transform", "depends_on": [1]},
    {"step_idx": 3, "text": "篩 is_ooc==true", "candidate_block": "block_filter",
     "expected_kind": "transform", "depends_on": [2]},
    {"step_idx": 4, "text": "依 eventTime groupby + count OOC SPCs", "candidate_block": "block_groupby_agg",
     "expected_kind": "transform", "depends_on": [3]},
    {"step_idx": 5, "text": "verdict: ooc_count >= 2", "candidate_block": "block_step_check",
     "expected_kind": "scalar", "depends_on": [4]},
    {"step_idx": 6, "text": "OOC 時刻所有 SPC chart panel (composite)", "candidate_block": "block_spc_panel",
     "expected_kind": "chart", "depends_on": [1]}
  ]
}
（step 5 verdict / step 6 chart 是 **平行 terminals** — step 6 直接從 step 1 的 source fan-out，
**不依賴 step 5**。chart 接在 verdict 後面是錯的：verdict 輸出 bool/scalar，給不出 dataframe）

範例 4-X (重要 — cross-branch join): User 說「找 EQP-07 最後一次 OOC 的時刻，列出該時刻所有 OOC SPC 的數值表 + 畫該時刻過去 7 天 trend」
✅ 正確（用 block_join 把 last OOC time 連回 OOC 全表）:
{
  "plan_summary": "verdict 分支找 last OOC time + table/chart 分支用 join 拉回該時刻 detail",
  "macro_plan": [
    {"step_idx": 1, "text": "撈 process_history nested", "candidate_block": "block_process_history",
     "expected_kind": "transform", "depends_on": []},
    {"step_idx": 2, "text": "展開 spc_charts", "candidate_block": "block_unnest",
     "expected_kind": "transform", "depends_on": [1]},
    {"step_idx": 3, "text": "篩 is_ooc==true", "candidate_block": "block_filter",
     "expected_kind": "transform", "depends_on": [2]},
    {"step_idx": 4, "text": "依 eventTime groupby + count", "candidate_block": "block_groupby_agg",
     "expected_kind": "transform", "depends_on": [3]},
    {"step_idx": 5, "text": "排序取 last OOC eventTime (desc, limit=1)", "candidate_block": "block_sort",
     "expected_kind": "transform", "depends_on": [4]},
    {"step_idx": 6, "text": "verdict ≥ threshold", "candidate_block": "block_step_check",
     "expected_kind": "scalar", "depends_on": [5]},
    {"step_idx": 7, "text": "JOIN step 3 OOC 全表 ⨯ step 5 last OOC time → 只剩該時刻 OOC rows",
     "candidate_block": "block_join", "expected_kind": "transform", "depends_on": [3, 5]},
    {"step_idx": 8, "text": "table 列出該時刻各 SPC 的 value/ucl/lcl",
     "candidate_block": "block_data_view", "expected_kind": "table", "depends_on": [7]},
    {"step_idx": 9, "text": "畫該時刻所有 SPC 過去 7 天 trend", "candidate_block": "block_line_chart",
     "expected_kind": "chart", "depends_on": [7]}
  ]
}
（step 7 用 **block_join** 把 last_OOC_time 跟 OOC 全表 join。**不要**用 block_filter literal，
那會強迫 LLM 幻覺出垃圾 value）

範例 4: User 說「列出 OOC table 並同時畫 trend + 觸發 alarm」(三 terminals)
✅ 三 branch 從共用上游 fan-out:
{
  "plan_summary": "table + chart + verdict — 三 terminal 各自 fan-out",
  "macro_plan": [
    {"step_idx": 1, "text": "撈 process_history", "candidate_block": "block_process_history",
     "expected_kind": "transform", "depends_on": []},
    {"step_idx": 2, "text": "展開 + 篩 OOC", "candidate_block": "block_unnest",
     "expected_kind": "transform", "depends_on": [1]},
    {"step_idx": 3, "text": "OOC 列表 (table terminal)", "candidate_block": "block_data_view",
     "expected_kind": "table", "depends_on": [2]},
    {"step_idx": 4, "text": "OOC trend chart (chart terminal)", "candidate_block": "block_line_chart",
     "expected_kind": "chart", "depends_on": [2]},
    {"step_idx": 5, "text": "verdict count >= threshold (alarm)", "candidate_block": "block_step_check",
     "expected_kind": "scalar", "depends_on": [2]}
  ]
}
（step 3/4/5 都從 step 2 fan-out — 共用同一個 OOC dataframe，三個 terminals 各自接）

如果 user 的需求過於模糊或不適合 build pipeline，回 {"too_vague": true, "reason": "..."}。

只輸出 JSON，無 markdown fence:

{
  "plan_summary": "<一句話描述要建什麼>",
  "macro_plan": [
    {
      "step_idx": 1,
      "text": "<這 step 做什麼，1 句中文>",
      "expected_kind": "transform" | "table" | "chart" | "scalar",
      "expected_cols": ["col1", "col2"] (僅給 user 看 confirm card 用的 hint — 寫 user 自然語言提到想看的欄位；不確定就 []。⚠ 這**不是** column ref 來源，compile_chunk 一律從 UPSTREAM TRACE 取真實欄位名),
      "candidate_block": "block_xxx" (從候選 blocks 清單挑),
      "depends_on": [<上游 step_idx>, ...] (source step 寫 []，必填)
    }
  ]
}
"""


_BLOCK_BRIEF_CACHE: str | None = None


def _format_block_briefs(catalog: dict) -> str:
    """Compact brief per block — block_id + What section + Output shape.

    macro_plan needs to know output shape to plan unnest / flatten steps
    correctly. Just the first line of description (`== What ==`) skips
    over the critical Output section that says "this block returns
    nested data — downstream needs unnest" for sources like
    block_process_history. Without it, macro_plan plans
    `groupby_agg → sort by eventTime` over data that has no eventTime
    column post-groupby.

    Strategy: pull `== What ==` section (1-3 lines) AND `== Output ==`
    section (capped to ~200 chars) per block. Cache the result; the
    catalog is constant per process.
    """
    global _BLOCK_BRIEF_CACHE
    if _BLOCK_BRIEF_CACHE is not None:
        return _BLOCK_BRIEF_CACHE
    lines: list[str] = []
    seen: set[str] = set()
    for (name, _version), spec in catalog.items():
        if name in seen:
            continue
        # v18: hide deprecated blocks from the planner. They're kept in
        # the registry for backwards-compat of saved pipelines but should
        # not be suggested to the LLM (e.g. legacy block_chart competes
        # with dedicated chart blocks and the LLM often picks it because
        # the description sounds general-purpose).
        if str(spec.get("status") or "").lower() == "deprecated":
            continue
        seen.add(name)
        desc = (spec.get("description") or "").strip()
        category = spec.get("category", "")
        what = _extract_section(desc, "What")
        output = _extract_section(desc, "Output")
        brief_parts: list[str] = []
        if what:
            brief_parts.append(what[:240])
        if output:
            brief_parts.append("output: " + output[:240])
        if not brief_parts:
            # Fallback: legacy desc without sections — take first 200 chars
            brief_parts.append(desc.split("\n\n", 1)[0][:200])
        brief = " | ".join(brief_parts)
        lines.append(f"- {name} ({category}): {brief}")
    lines.sort()
    _BLOCK_BRIEF_CACHE = "\n".join(lines)
    return _BLOCK_BRIEF_CACHE


def _extract_section(desc: str, header: str) -> str:
    """Pull a `== Header ==` section from a description, return its body
    (lines until the next `== Other ==` header), trimmed and joined as
    one line.  Empty string if section not found.
    """
    marker = f"== {header} =="
    idx = desc.find(marker)
    if idx < 0:
        return ""
    body_start = idx + len(marker)
    rest = desc[body_start:]
    # Find next "== ... ==" header to stop at
    next_marker = re.search(r"\n==\s+\S+\s+==", rest)
    section = rest[:next_marker.start()] if next_marker else rest
    # Collapse newlines + extra whitespace into single spaces
    return " ".join(section.split())


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def macro_plan_node(state: BuildGraphState) -> dict[str, Any]:
    """Emits a 5-10 step natural-language macro plan."""
    from python_ai_sidecar.pipeline_builder.seedless_registry import SeedlessBlockRegistry
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )

    registry = SeedlessBlockRegistry()
    registry.load()
    briefs = _format_block_briefs(registry.catalog)

    instruction = state.get("instruction") or ""
    skill_step_mode = bool(state.get("skill_step_mode"))
    base_pipeline = state.get("base_pipeline") or {}

    declared_inputs = base_pipeline.get("inputs") or []
    inputs_section = ""
    if declared_inputs:
        bullets: list[str] = []
        for inp in declared_inputs:
            if not isinstance(inp, dict):
                continue
            name = inp.get("name")
            if not name:
                continue
            canon = _canonical_lookup(name) or {}
            itype = inp.get("type") or canon.get("type") or "string"
            req = " required" if inp.get("required") else ""
            sample = (
                inp.get("example")
                if inp.get("example") is not None
                else (inp.get("default") if inp.get("default") is not None else canon.get("sample"))
            )
            desc = inp.get("description") or canon.get("description") or ""
            sample_str = f", e.g. {sample!r}" if sample is not None else ""
            bullets.append(
                f"  - ${name} ({itype}{req}){sample_str}"
                + (f" — {desc}" if desc else "")
            )
        if bullets:
            inputs_section = "\n\nPipeline INPUTS（用 $name 引用）:\n" + "\n".join(bullets)
    # v21: surface trigger payload shape (process_event / alarm / patrol / manual)
    meta = base_pipeline.get("metadata") or {}
    trigger_section = _format_trigger(meta.get("trigger_kind") or meta.get("trigger"))

    # In skill mode, the terminal must be a verdict-shaped block (output
    # carries a pass/fail signal) so SkillRunner can read pass/fail. We
    # don't name the specific block here — let the LLM pick from the
    # candidate list using each block's Output brief. Deterministic
    # post-checks below enforce the shape.
    skill_section = (
        "\n\n⚠ SKILL STEP MODE — 終點必須是 verdict 形狀的 block（看 brief 的 output 是 bool/verdict 那種，"
        "讓 runner 讀 pass/fail）。"
        if skill_step_mode else ""
    )

    user_msg = (
        f"USER NEED:\n{instruction[:2000]}"
        f"{inputs_section}"
        f"{trigger_section}"
        f"{skill_section}"
        f"\n\n候選 blocks (你可以選):\n{briefs}"
    )

    client = get_llm_client()
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )
    tracer = get_current_tracer()
    extra_sse: list[dict[str, Any]] = []

    raw_text = ""
    try:
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
            decision = _extract_first_json_object(text or "")
    except Exception as ex:  # noqa: BLE001
        logger.warning("macro_plan_node: LLM/parse failed (%s)", ex)
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=None, error=str(ex)[:300],
            )
            tracer.record_step("macro_plan_node", status="failed", error=str(ex)[:300])
        return {
            "macro_plan": [],
            "plan_validation_errors": [f"macro_plan failed: {ex}"],
            "status": "failed",
            "summary": f"macro_plan failed: {ex}",
            "sse_events": [_event("macro_plan_failed", {"error": str(ex)[:200]})],
        }

    if isinstance(decision, dict) and decision.get("too_vague"):
        reason = str(decision.get("reason") or "instruction too vague to build a pipeline")
        # v18 (2026-05-14): reject-and-ask loop. Don't silent-fail. Route
        # back to clarify_intent up to MAX_TOO_VAGUE_ATTEMPTS=2 with the
        # reason as context for asking targeted questions; after that,
        # explicitly refuse with a friendly message.
        attempts = int(state.get("too_vague_attempts") or 0) + 1
        is_refused = attempts >= MAX_TOO_VAGUE_ATTEMPTS
        next_status = "refused" if is_refused else "needs_clarify"
        logger.info(
            "macro_plan_node: too_vague — attempt=%d/%d → %s — %s",
            attempts, MAX_TOO_VAGUE_ATTEMPTS, next_status, reason[:120],
        )
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=decision, verdict="too_vague",
                resp=resp,
            )
            tracer.record_step(
                "macro_plan_node", status=next_status,
                attempt=attempts, reason=reason[:300],
            )
        if is_refused:
            return {
                "macro_plan": [],
                "plan_validation_errors": [f"refused: {reason}"],
                "summary": (
                    "我搞不懂這個需求 — 試了 2 次都覺得太模糊。請更具體描述：你要看什麼資料？"
                    "預期輸出是什麼？要看哪台機台 / 哪段時間？"
                ),
                "status": "refused",
                "too_vague_attempts": attempts,
                "too_vague_reason": reason[:500],
                "sse_events": [_event("macro_plan_refused", {"reason": reason[:300]})],
            }
        # Route back to clarify_intent for another pass.
        return {
            "macro_plan": [],
            "summary": f"Need clarification — {reason[:200]}",
            "status": "needs_clarify",
            "too_vague_attempts": attempts,
            "too_vague_reason": reason[:500],
            # Reset clarify_attempts so clarify_intent re-runs (it short-
            # circuits when clarify_attempts >= 1).
            "clarify_attempts": 0,
            "sse_events": [_event("macro_plan_needs_clarify", {"reason": reason[:300]})],
        }

    raw_macro = (decision or {}).get("macro_plan") or []
    # Catalog lookup: block_id → output port types. Used by the chat-mode
    # filter below — drop any step whose candidate_block emits a non-data
    # type (bool / verdict), since chat terminals must be chart/table/scalar.
    # Looked up from registry instead of hard-coding block names.
    bool_output_blocks: set[str] = set()
    for (name, _v), spec in registry.catalog.items():
        ports = spec.get("output_schema") or []
        if any(isinstance(p, dict) and p.get("type") in {"bool", "verdict"} for p in ports):
            bool_output_blocks.add(name)

    macro_plan: list[dict[str, Any]] = []
    if isinstance(raw_macro, list):
        for i, item in enumerate(raw_macro[:MAX_MACRO_STEPS], 1):
            if not isinstance(item, dict):
                continue
            step_idx = item.get("step_idx", i)
            text_val = str(item.get("text") or "").strip()
            if not text_val:
                continue
            candidate_block = str(item.get("candidate_block") or "")
            # Chat mode terminals must carry data (chart/table/scalar); drop
            # any LLM-suggested step whose candidate_block emits bool/verdict.
            if not skill_step_mode and candidate_block in bool_output_blocks:
                logger.info(
                    "macro_plan_node: dropped step_idx=%s candidate=%s (verdict-shaped block forbidden in chat mode)",
                    step_idx, candidate_block,
                )
                continue
            # v20: depends_on (DAG schema). Mandatory per CLAUDE.md;
            # validation below rejects missing field. Coerce ints, drop
            # any element that's not a positive int.
            raw_dep = item.get("depends_on")
            dep_list: list[int] = []
            dep_present = raw_dep is not None
            if isinstance(raw_dep, list):
                for d in raw_dep:
                    try:
                        di = int(d)
                        if di > 0:
                            dep_list.append(di)
                    except (TypeError, ValueError):
                        pass
            macro_plan.append({
                "step_idx": int(step_idx),
                "text": text_val,
                "expected_kind": str(item.get("expected_kind") or "transform"),
                "expected_cols": list(item.get("expected_cols") or []),
                "candidate_block": candidate_block,
                "depends_on": dep_list,
                "_dep_present": dep_present,  # internal — stripped before SSE
                "completed": False,
                "ops_appended": 0,
            })
    # Renumber step_idx after any drops so compile_chunk doesn't see gaps.
    # CRITICAL: when we renumber, also remap depends_on so old indices stay
    # valid. Build {old_idx: new_idx} map first, then walk depends_on.
    old_to_new = {step["step_idx"]: new_i for new_i, step in enumerate(macro_plan, 1)}
    for new_i, step in enumerate(macro_plan, 1):
        step["step_idx"] = new_i
        step["depends_on"] = [
            old_to_new[d] for d in step.get("depends_on") or [] if d in old_to_new
        ]

    if not macro_plan:
        if tracer is not None:
            tracer.record_llm(
                "macro_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=decision, verdict="empty_after_parse",
                resp=resp,
            )
            tracer.record_step(
                "macro_plan_node", status="failed",
                reason="macro_plan empty after parsing (no valid steps)",
            )
        return {
            "macro_plan": [],
            "plan_validation_errors": ["macro_plan empty after parsing"],
            "summary": "(macro plan generation failed — model returned no valid steps)",
            "status": "failed",
            "sse_events": [_event("macro_plan_failed", {"reason": "no valid steps"})],
        }

    summary = str(decision.get("plan_summary") or "(no summary)").strip() or "(no summary)"

    logger.info(
        "macro_plan_node: produced %d steps (max=%d), summary=%r",
        len(macro_plan), MAX_MACRO_STEPS, summary[:80],
    )

    # v20 (2026-05-15): DAG schema validation.
    # depends_on must be present on every step; a missing field counts as
    # too_vague (loop back to clarify_intent so we don't silently auto-link).
    # Forward refs / refs to non-existent step_idx also fail. No upper bound
    # on parallel branch count — user explicitly asked for "no branch limit".
    dag_errors: list[str] = []
    valid_indices = {s["step_idx"] for s in macro_plan}
    for s in macro_plan:
        idx = s["step_idx"]
        if not s.pop("_dep_present", False):
            dag_errors.append(f"step {idx}: missing required `depends_on` field")
            continue
        deps = s.get("depends_on") or []
        # Source steps (depends_on=[]) only allowed on step_idx==1, OR on a
        # subsequent step that's a separate source (e.g. multiple parallel
        # source fetches — rare but legitimate). LLM can do step_1 source +
        # step_N=another source → both depends_on=[].
        for d in deps:
            if d >= idx:
                dag_errors.append(
                    f"step {idx}: depends_on={deps} contains forward/self ref {d} "
                    f"(must be < {idx})"
                )
            elif d not in valid_indices:
                dag_errors.append(
                    f"step {idx}: depends_on={deps} references missing step {d}"
                )

    if dag_errors:
        attempts_d = int(state.get("too_vague_attempts") or 0) + 1
        is_refused_d = attempts_d >= MAX_TOO_VAGUE_ATTEMPTS
        next_status_d = "refused" if is_refused_d else "needs_clarify"
        dag_reason = (
            "macro_plan DAG validation failed: " + "; ".join(dag_errors[:5])
            + " — every step must declare `depends_on: [parent_step_idx,...]` "
            "(use [] for source steps). Forward refs and dangling refs are "
            "rejected. This is required so parallel branches (chart + verdict) "
            "are explicit instead of silent linear chaining."
        )
        logger.warning(
            "macro_plan_node: DAG validation FAIL — attempt=%d/%d → %s — %d errors",
            attempts_d, MAX_TOO_VAGUE_ATTEMPTS, next_status_d, len(dag_errors),
        )
        if tracer is not None:
            tracer.record_step(
                "macro_plan_node", status=next_status_d,
                attempt=attempts_d, reason=dag_reason[:300],
                rule="dag_required", dag_errors=dag_errors[:10],
            )
        if is_refused_d:
            return {
                "macro_plan": [],
                "plan_validation_errors": [dag_reason],
                "summary": "建構失敗 — model 給的 macro_plan 無法描述 DAG (depends_on 缺漏或亂指)",
                "status": "refused",
                "too_vague_attempts": attempts_d,
                "too_vague_reason": dag_reason[:500],
            }
        return {
            "macro_plan": [],
            "summary": "Need clarification — DAG depends_on missing/invalid",
            "status": "needs_clarify",
            "too_vague_attempts": attempts_d,
            "too_vague_reason": dag_reason[:500],
            "clarify_attempts": 0,
            "sse_events": [_event("macro_plan_needs_clarify", {"reason": dag_reason[:300]})],
        }

    # Strip internal _dep_present flag from any step that didn't trigger error
    # path above (defensive — should already be popped, but list comprehensions
    # over edge cases may have left some).
    for s in macro_plan:
        s.pop("_dep_present", None)

    # v19 (2026-05-15): chart-required post-check.
    # When the user instruction explicitly asks for visualization (顯示 / chart
    # / 圖表 / plot / 趨勢 / show / visualize) but macro_plan produced no
    # chart-output terminal, treat as too_vague and loop back to clarify_intent.
    # User feedback: skill C1 "OOC 跨 chart 聯防" 5/5 runs — 2/5 had only
    # verdict (step_check) and no chart at all, violating the explicit
    # "顯示該 SPC charts" requirement.
    _VIZ_KEYWORDS = ("顯示", "趨勢", "圖表", "趨勢圖", "畫", "看", "show", "chart", "plot", "visualize", "graph")
    _CHART_OUTPUT_BLOCKS = {
        "block_line_chart", "block_bar_chart", "block_scatter_chart",
        "block_box_plot", "block_histogram_chart", "block_splom",
        "block_xbar_r", "block_imr", "block_ewma_cusum", "block_pareto",
        "block_variability_gauge", "block_parallel_coords",
        "block_probability_plot", "block_heatmap_dendro",
        "block_wafer_heatmap", "block_defect_stack", "block_spatial_pareto",
        "block_trend_wafer_maps",
        "block_spc_panel", "block_apc_panel",
    }
    instr_lower = (instruction or "").lower()
    asks_for_viz = any(kw.lower() in instr_lower for kw in _VIZ_KEYWORDS)
    has_chart_terminal = any(
        s.get("candidate_block") in _CHART_OUTPUT_BLOCKS
        or s.get("expected_kind") == "chart"
        for s in macro_plan
    )
    if asks_for_viz and not has_chart_terminal:
        attempts_v = int(state.get("too_vague_attempts") or 0) + 1
        is_refused = attempts_v >= MAX_TOO_VAGUE_ATTEMPTS
        next_status = "refused" if is_refused else "needs_clarify"
        chart_reason = (
            "User explicitly asked for visualization (keyword detected: "
            f"{[k for k in _VIZ_KEYWORDS if k.lower() in instr_lower][:3]}) "
            "but the produced macro_plan has no chart-output terminal "
            "(no block_*_chart, block_*_panel, block_*_plot, etc.). "
            "Skill_step_mode pipelines that need a chart must include both "
            "a verdict terminal (block_step_check) AND a chart terminal in "
            "parallel branches (fan-out from block_process_history)."
        )
        logger.warning(
            "macro_plan_node: chart-required check FAIL — attempt=%d/%d → %s",
            attempts_v, MAX_TOO_VAGUE_ATTEMPTS, next_status,
        )
        if tracer is not None:
            tracer.record_step(
                "macro_plan_node", status=next_status,
                attempt=attempts_v, reason=chart_reason[:300],
                rule="chart_required",
            )
        if is_refused:
            return {
                "macro_plan": [],
                "plan_validation_errors": [chart_reason],
                "summary": "建構失敗 — 你要看 chart 但 model 給不出 chart 終端",
                "status": "refused",
                "too_vague_attempts": attempts_v,
                "too_vague_reason": chart_reason[:500],
            }
        return {
            "macro_plan": [],
            "summary": "Need clarification — visualization terminal missing",
            "status": "needs_clarify",
            "too_vague_attempts": attempts_v,
            "too_vague_reason": chart_reason[:500],
            "clarify_attempts": 0,  # let clarify_intent re-run
            "sse_events": [_event("macro_plan_needs_clarify", {"reason": chart_reason[:300]})],
        }

    if tracer is not None:
        step_entry = tracer.record_step(
            "macro_plan_node", status="ok",
            n_steps=len(macro_plan), summary=summary[:200],
        )
        sse = trace_event_to_sse(step_entry, kind="step")
        if sse: extra_sse.append(sse)
        llm_entry = tracer.record_llm(
            node="macro_plan_node",
            system=_SYSTEM[:300] + "…",
            user_msg=user_msg[:1500],
            raw_response=resp.text or "",
            parsed=decision,
            resp=resp,
        )
        sse2 = trace_event_to_sse(llm_entry, kind="llm_call")
        if sse2: extra_sse.append(sse2)

    return {
        "macro_plan": macro_plan,
        "current_macro_step": 0,
        "compile_attempts": {},
        "summary": summary,
        "is_from_scratch": True,  # v16 always treats macro+chunk as from-scratch
        "plan_validation_errors": [],
        "sse_events": [
            _event("macro_plan_proposed", {
                "summary": summary,
                "macro_plan": [
                    {k: v for k, v in s.items() if k not in {"completed", "ops_appended"}}
                    for s in macro_plan
                ],
                "n_steps": len(macro_plan),
            }),
            *extra_sse,
        ],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
