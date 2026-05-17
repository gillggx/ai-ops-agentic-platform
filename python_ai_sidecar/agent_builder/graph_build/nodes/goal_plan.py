"""v30 goal_plan_node — emit goal-oriented phases (no block selection yet).

Replaces macro_plan_node. Output is 3-7 phases each describing an outcome
the build must achieve, with `expected` category for downstream verifier.

LLM is NOT allowed to pick specific blocks here — that's the job of
agentic_phase_loop which can see real data. goal_plan_node operates on:
  - user instruction
  - bullets (legacy bridge — still emits but not strictly required)
  - canvas snapshot if base_pipeline non-empty
  - high-level block category briefs (NOT individual block params)

After emission, graph routes to goal_plan_confirm_gate which interrupt()s
and waits for user confirm/edit via /agent/build/plan-confirm endpoint.
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


MAX_PHASES = 7
MIN_PHASES = 1
VALID_EXPECTED = {
    "raw_data", "transform", "verdict", "chart", "table", "scalar", "alarm",
}


_SYSTEM = """你是 pipeline architect。User 給你需求，你產出 3-7 個 **goal-oriented phases**
描述「要達到什麼狀態」，**不挑具體 block**。

每個 phase:
  - `id`: "p1" / "p2" / ...
  - `goal`: 一句中文，描述這 phase 完成後 canvas 該有什麼資料 / 結果
  - `expected`: 完成類別，從以下 7 選 1:
      raw_data   — 取得原始 dataset
      transform  — 中繼 dataframe (filter/sort/agg 結果)
      verdict    — pass/fail 判定 (block_step_check 系列)
      chart      — chart_spec 輸出
      table      — block_data_view 表格
      scalar     — 單一數值
      alarm      — 觸發告警
  - `expected_output`: **必填** — 描述「實際算出什麼」的具體 outcome：
      {
        "kind": "scalar_with_context" | "chart_list" | "table" | "raw_rows" | "alarm" | "transform_rows",
        "value_desc": "OOC chart 實際張數 (int) + 該時刻 lot/tool/step",   # 真實算出的「東西」，不是 true/false
        "criterion": "ooc_count >= 2 視為通過判定",                          # 判定條件 (verdict 才填)
        "outcome_keys": ["ooc_count"]                                        # 給 verifier 抽值用的 key 提示 (1-3 個)
      }
  - `why`: (選填) 為什麼需要這 phase

**輸出 schema (JSON 純 — 無 markdown fence):**
{
  "plan_summary": "...一句話...",
  "phases": [
    {"id":"p1","goal":"取得 EQP-08 過去 7 天的歷史資料","expected":"raw_data",
     "expected_output":{"kind":"raw_rows","value_desc":"該機台過去 7 天每筆事件記錄","outcome_keys":["row_count"]},
     "why":"先 7d 試，沒資料退到 30d"},
    {"id":"p2","goal":"判斷該機台最後一次 OOC 時刻同時 OOC 的圖表數量是否達門檻 (≥2)","expected":"verdict",
     "expected_output":{"kind":"scalar_with_context","value_desc":"OOC 圖表實際張數 + 該時刻的批次/機台/站點","criterion":"圖表數 >= 2","outcome_keys":["ooc_chart_count"]}},
    {"id":"p3","goal":"展示該時刻所有 OOC 圖表的走勢與管制狀態","expected":"chart",
     "expected_output":{"kind":"chart_list","value_desc":"N 張 OOC 圖表的歷史走勢圖","outcome_keys":["chart_list"]}}
  ],
  "alarm": null
}

**核心原則：Plan 層只有 INTENTION，不碰工具與資料結構。**

你只負責把 user 講的事情翻成「想要的結果」的階段性描述。**禁止**出現任何：
  (a) Block 名稱：process_history / spc_panel / step_check / block_xxx 等
  (b) 資料結構 / 欄位名稱：spc_summary / spc_charts / ooc_count / nested / column /
      eventTime / spc_status / fdc_classification 等
  (c) 操作動詞綁定特定工具：unnest / sort+limit / groupby / pluck 等

只用 **user 的業務語言**：「歷史資料」「OOC 事件」「圖表數量」「管制狀態」「最後一次」「達門檻」等。

**反例 (錯誤 — 洩漏資料結構 / 工具)**:
  ❌ "撈取 EQP-08 過去 7 天 process_history 資料及其 spc_summary nested"
  ❌ "從 process_history 中找出最後一筆記錄"
  ❌ "判定 spc_summary.ooc_count > 2"
  ❌ "為每張 OOC chart 產生 SPC line chart visualization"
  ❌ "從 spc_summary 提取 chart_name、value、UCL、LCL、ooc_flag"

**正例 (對 — 純 intention)**:
  ✅ "取得 EQP-08 過去 7 天的歷史資料"
  ✅ "找出最後一次 OOC 事件的時刻"
  ✅ "判定該時刻 OOC 圖表數量是否達門檻 (≥2)"
  ✅ "展示各 OOC 圖表的走勢與管制狀態"
  ✅ "列出該時刻所有 OOC 圖表的數值與管制資訊"

**其它規則**:
1. phases 是線性順序，但**不寫 depends_on** — 後續 react_round 自己 wire
2. 一個 chart + 一個 verdict 都各 1 phase，**不要塞同 phase**
3. 若 user instruction 過模糊：回 {"too_vague": true, "reason": "..."}
4. **expected_output.value_desc 寫實際算出的「東西」**（一個數字、一張圖、一個列表），
   **不要**寫 "true/false" 這種抽象判定。執行層會把實際值（e.g. ooc 圖表數 = 3）
   填進 outcome 報告給 user 看。**value_desc 也禁止洩漏 column 名**。
5. **phase 切細沒關係** — 執行層會自動偵測「一個 block 涵蓋多 phase」並 fast-forward。
   你只負責把 user intent 拆成最小語意單位即可，不用怕太細。

== Phase Atomicity (極重要！) ==
每個 phase **必須是 1-2 個 block 能完成的單一資料動作**。**不要**把多動作塞同 phase。

❌ Bad — 「取得 + 找 last X」(2 動作擠 1 phase):
  p1: 取得過去 7 天資料並找出最後一次 OOC 事件的時刻 (raw_data)
✅ Good — 拆成 2 phase:
  p1: 取得 EQP-08 過去 7 天的歷史資料 (raw_data)
  p2: 找出最後一次 OOC 事件的時刻 (transform)

❌ Bad — 「計算 + 判定」混用 (動詞曖昧):
  p3: 統計該時刻同時 OOC 圖表數並判斷是否達門檻 (transform/verdict?)
✅ Good — 視 user 意圖二擇一:
  方案 A (分 2 phase): p3 統計 (scalar) + p4 判定 (verdict)
  方案 B (合為 1 phase): p3 判定該時刻同時 OOC 圖表數是否達門檻 (verdict)
  ※ 若 user 只關心「是否達門檻」就選 B；若需要先看「實際數量」再決定門檻才選 A

**檢查表**：寫完每 phase 自問:
  - 這 phase 能否用 **1 個 block** 完成？(2 個極限)
  - goal 描述裡有沒有「並 / 加上 / 同時 / + / 然後」這種連接詞？有 → 拆 (或合)。
  - phase.goal 是「取得 X」還是「找出 last X / 計算 Y / 展示 Z」？
    取得 + 加工 一定要拆。

**所有 example 一律用業務語言**（不出現任何 block 名稱、column 名稱、操作動詞綁定）。

預期 phase 數量：**4-7 phase 是常態**，太少代表把多動作擠在一起、太多代表過分細碎。
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text.strip()).strip()


async def goal_plan_node(state: BuildGraphState) -> dict[str, Any]:
    """Emit 3-7 goal-oriented phases."""
    from python_ai_sidecar.agent_builder.graph_build.nodes.plan import (
        _extract_first_json_object,
    )
    from python_ai_sidecar.agent_builder.graph_build.trace import (
        get_current_tracer, trace_event_to_sse,
    )

    instruction = state.get("instruction") or ""
    base_pipeline = state.get("base_pipeline") or {}
    skill_step_mode = bool(state.get("skill_step_mode"))

    # Existing canvas snapshot — if user has manual nodes, list them so LLM
    # can plan incrementally instead of from-scratch overwriting.
    existing_nodes_section = ""
    if base_pipeline.get("nodes"):
        node_summaries = [
            f"  {n.get('id')} [{n.get('block_id')}] params={n.get('params')}"
            for n in base_pipeline["nodes"][:10]
        ]
        existing_nodes_section = (
            "\n\nCANVAS 已有 nodes (incremental mode):\n"
            + "\n".join(node_summaries)
            + ("\n... + more" if len(base_pipeline["nodes"]) > 10 else "")
        )

    # Declared inputs (compact)
    declared_inputs = base_pipeline.get("inputs") or []
    inputs_section = ""
    if declared_inputs:
        names = [inp.get("name") for inp in declared_inputs if isinstance(inp, dict)]
        inputs_section = (
            f"\n\nPipeline declared inputs (referenceable as $name): "
            f"{', '.join('$' + n for n in names if n)}"
        )

    skill_section = (
        "\n\nSKILL STEP MODE: final phase must produce a verdict (pass/fail)."
        if skill_step_mode else ""
    )

    user_msg = (
        f"USER NEED:\n{instruction[:2000]}"
        f"{inputs_section}"
        f"{skill_section}"
        f"{existing_nodes_section}"
    )

    client = get_llm_client()
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
        logger.warning("goal_plan_node: LLM/parse failed (%s)", ex)
        if tracer is not None:
            tracer.record_llm(
                "goal_plan_node", system=_SYSTEM, user_msg=user_msg,
                raw_response=raw_text, parsed=None, error=str(ex)[:300],
            )
            tracer.record_step("goal_plan_node", status="failed", error=str(ex)[:300])
        return {
            "v30_phases": [],
            "status": "failed",
            "summary": f"goal_plan failed: {ex}",
            "sse_events": [_event("goal_plan_failed", {"error": str(ex)[:200]})],
        }

    # too_vague path
    if isinstance(decision, dict) and decision.get("too_vague"):
        reason = str(decision.get("reason") or "instruction too vague")
        logger.info("goal_plan_node: too_vague — %s", reason[:120])
        if tracer is not None:
            tracer.record_step(
                "goal_plan_node", status="refused", verdict="too_vague",
                reason=reason[:300],
            )
        return {
            "v30_phases": [],
            "status": "refused",
            "summary": f"我搞不懂這個需求 — {reason[:200]}。請更具體描述：要看什麼資料/預期輸出/哪台機台。",
            "sse_events": [_event("goal_plan_refused", {"reason": reason[:300]})],
        }

    # Parse + validate phases
    raw_phases = (decision or {}).get("phases") or []
    phases: list[dict[str, Any]] = []
    for i, item in enumerate(raw_phases[:MAX_PHASES], 1):
        if not isinstance(item, dict):
            continue
        goal = str(item.get("goal") or "").strip()
        if not goal:
            continue
        expected = str(item.get("expected") or "transform").strip().lower()
        if expected not in VALID_EXPECTED:
            logger.warning(
                "goal_plan_node: phase %s invalid expected=%r, falling back to 'transform'",
                item.get("id") or f"p{i}", expected,
            )
            expected = "transform"
        # expected_output (v30.1) — sanitize but pass through. Verifier
        # tolerates missing fields (falls back to kind-only match).
        eo_raw = item.get("expected_output") or {}
        expected_output = None
        if isinstance(eo_raw, dict):
            outcome_keys = eo_raw.get("outcome_keys") or []
            if not isinstance(outcome_keys, list):
                outcome_keys = []
            expected_output = {
                "kind": str(eo_raw.get("kind") or "").strip() or None,
                "value_desc": str(eo_raw.get("value_desc") or "").strip() or None,
                "criterion": str(eo_raw.get("criterion") or "").strip() or None,
                "outcome_keys": [str(k).strip() for k in outcome_keys[:5] if k],
            }
        phases.append({
            "id": str(item.get("id") or f"p{i}").strip(),
            "goal": goal,
            "expected": expected,
            "expected_output": expected_output,
            "why": str(item.get("why") or "").strip() or None,
            "user_edited": False,
        })

    if len(phases) < MIN_PHASES:
        logger.info("goal_plan_node: empty phases after parse")
        if tracer is not None:
            tracer.record_step(
                "goal_plan_node", status="failed",
                reason="no valid phases after parse",
            )
        return {
            "v30_phases": [],
            "status": "failed",
            "summary": "(goal_plan produced no valid phases)",
            "sse_events": [_event("goal_plan_failed", {"reason": "no valid phases"})],
        }

    plan_summary = str(decision.get("plan_summary") or "").strip() or "(no summary)"
    alarm = decision.get("alarm")  # optional, can be None

    logger.info(
        "goal_plan_node: emitted %d phases, summary=%r",
        len(phases), plan_summary[:80],
    )

    if tracer is not None:
        llm_entry = tracer.record_llm(
            node="goal_plan_node",
            system=_SYSTEM[:300] + "...",
            user_msg=user_msg[:1500],
            raw_response=raw_text,
            parsed=decision,
            resp=resp,
        )
        sse = trace_event_to_sse(llm_entry, kind="llm_call")
        if sse: extra_sse.append(sse)
        step_entry = tracer.record_step(
            "goal_plan_node", status="ok",
            n_phases=len(phases), summary=plan_summary[:200],
            phases=phases,
        )
        sse2 = trace_event_to_sse(step_entry, kind="step")
        if sse2: extra_sse.append(sse2)
        # v30.1.1: per-emitted-phase candidate analysis. Even though
        # goal_plan is block-agnostic by design, recording what blocks
        # WOULD have satisfied each phase tells us at debug-time whether
        # the plan is implementable by 1-block solutions (and which ones).
        try:
            from python_ai_sidecar.agent_builder.graph_build.trace_helpers import (
                build_decision_metadata,
            )
            from python_ai_sidecar.pipeline_builder.seedless_registry import (
                SeedlessBlockRegistry,
            )
            registry = SeedlessBlockRegistry(); registry.load()
            phase_analyses = []
            for i, ph in enumerate(phases):
                meta = build_decision_metadata(
                    phase=ph,
                    remaining_phases=phases[i + 1:],
                    registry=registry,
                    actual_pick_block=None,  # plan layer doesn't pick
                )
                phase_analyses.append(meta)
            tracer.record_decision(
                node="goal_plan_node",
                user_msg_sections={
                    "instruction_preview": (instruction or "")[:600],
                    "declared_inputs": [
                        i.get("name") for i in (declared_inputs or [])
                        if isinstance(i, dict)
                    ],
                    "skill_step_mode": skill_step_mode,
                    "existing_canvas_node_count": len(base_pipeline.get("nodes") or []),
                },
                llm_response={
                    "text_blocks": [],  # JSON output — no narrative text
                    "tool_use": None,
                    "emitted_phases": [
                        {"id": p["id"], "expected": p["expected"], "goal": p["goal"][:80]}
                        for p in phases
                    ],
                },
                decision_metadata={
                    "per_phase_analysis": phase_analyses,
                    "n_phases_with_fast_forward_solution": sum(
                        1 for a in phase_analyses if a.get("fast_forward_capable_blocks")
                    ),
                },
            )
        except Exception as ex:  # noqa: BLE001
            logger.info("trace.record_decision (goal_plan) failed (non-fatal): %s", ex)

    return {
        "v30_phases": phases,
        "v30_current_phase_idx": 0,
        "v30_phase_round": 0,
        "v30_phase_outcomes": {},
        "v30_handover": None,
        "v30_phase_edit_history": {},
        "v30_phase_recent_actions": {},
        "summary": plan_summary,
        "status": "goal_plan_confirm_required",
        "is_from_scratch": not bool(base_pipeline.get("nodes")),
        "sse_events": [
            _event("goal_plan_proposed", {
                "plan_summary": plan_summary,
                "phases": phases,
                "alarm": alarm,
                "n_phases": len(phases),
            }),
            *extra_sse,
        ],
    }


async def goal_plan_confirm_gate_node(state: BuildGraphState) -> dict[str, Any]:
    """Interrupt the graph; wait for user to confirm/edit phases.

    User can send back: {confirmed: true, phases: [...edited...]}
    OR              : {confirmed: false}  (abort)

    v30.17a (2026-05-17) — skip_confirm bypass. When the caller passed
    skip_confirm=True (chat orchestrator's build_pipeline_live tool,
    skill_translate flow, etc.), the conversation itself is the
    confirmation — no explicit gate needed. Auto-confirm + emit a
    goal_plan_confirmed SSE event so the graph proceeds straight to
    agentic_phase_loop without interrupt. Without this, chat callers
    silently stall here: tool_execute returns an empty stream, chat LLM
    writes a generic reply, user UI never sees the build progress.
    """
    phases = state.get("v30_phases") or []
    plan_summary = state.get("summary") or "(no summary)"

    if state.get("skip_confirm"):
        logger.info(
            "goal_plan_confirm_gate: skip_confirm=True — auto-confirming %d phases",
            len(phases),
        )
        return {
            "status": "phase_in_progress",
            "v30_current_phase_idx": 0,
            "v30_phase_round": 0,
            "sse_events": [_event("goal_plan_confirmed", {
                "phases": phases,
                "n_edits": 0,
                "auto_confirmed": True,
            })],
        }

    logger.info(
        "goal_plan_confirm_gate: pausing for user — %d phases",
        len(phases),
    )

    user_response = interrupt({
        "kind": "goal_plan_confirm_required",
        "session_id": state.get("session_id"),
        "plan_summary": plan_summary,
        "phases": phases,
    })

    # User confirmed — possibly with edits
    if not isinstance(user_response, dict):
        user_response = {"confirmed": bool(user_response)}

    if not user_response.get("confirmed"):
        logger.info("goal_plan_confirm_gate: user rejected build")
        return {
            "status": "refused",
            "summary": "User rejected the proposed phases.",
            "sse_events": [_event("goal_plan_rejected", {})],
        }

    # If user sent edited phases, use them verbatim. Track edit history.
    edited_phases_raw = user_response.get("phases")
    if isinstance(edited_phases_raw, list) and edited_phases_raw:
        original = {p["id"]: p for p in phases}
        edit_history: dict[str, list[dict]] = {}
        new_phases: list[dict[str, Any]] = []
        for i, item in enumerate(edited_phases_raw[:MAX_PHASES], 1):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("id") or f"p{i}")
            goal = str(item.get("goal") or "").strip()
            if not goal:
                continue
            expected = str(item.get("expected") or "transform").lower()
            if expected not in VALID_EXPECTED:
                expected = "transform"
            orig = original.get(pid)
            edited = orig is None or orig.get("goal") != goal
            # Keep expected_output from original if user didn't supply one
            # (UI may not surface it for editing yet; preserve LLM's emit).
            eo_raw = item.get("expected_output")
            if not isinstance(eo_raw, dict):
                eo_raw = (orig or {}).get("expected_output")
            new_phases.append({
                "id": pid, "goal": goal, "expected": expected,
                "expected_output": eo_raw,
                "why": str(item.get("why") or "").strip() or None,
                "user_edited": edited,
            })
            if edited and orig:
                edit_history.setdefault(pid, []).append({
                    "from": orig.get("goal"), "to": goal,
                })
        phases = new_phases
        logger.info(
            "goal_plan_confirm_gate: user edited %d phase(s)",
            sum(1 for p in phases if p.get("user_edited")),
        )
        return {
            "v30_phases": phases,
            "v30_phase_edit_history": edit_history,
            "status": "phase_in_progress",
            "sse_events": [_event("goal_plan_confirmed", {
                "phases": phases, "n_edits": len(edit_history),
            })],
        }

    # User confirmed without edits
    return {
        "status": "phase_in_progress",
        "sse_events": [_event("goal_plan_confirmed", {
            "phases": phases, "n_edits": 0,
        })],
    }


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}
