# Multi-Agent Build 平面 — 設計 + Phase 0 Tech Spec

> Draft v3（細化版）· 2026-07-02。承接 `AGENT_HARNESS_DESIGN.html` / `MULTI_AGENT_ARCHITECTURE.html`。
> 決策前提:D1 = 結構重構先;D2 = 監控平面納入本 effort（Phase 1）。
>
> **界線**:本文把 Planner/Builder/Repair 的**目標互動契約**先完整定義（含 schema 與介面簽名），
> Phase 0 實際只做「把現有 flow 包成 agent + registry、零行為改變」。每段標清楚
> 「Phase 0 就做」vs「介面先定、Phase 2+ 長行為」。

---

## 1. Context & Objective

**現況**:builder 是單一 LangGraph、單一 LLM、單一 prompt 語境。
`goal_plan` / `agentic_phase_loop` / `phase_verifier` / `phase_revise` 是 node，但共用一切
（現行檔案:`python_ai_sidecar/agent_builder/graph_build/graph.py` + `nodes/*.py`）。

**目標**:拆成 **Planner / Builder / Repair** 三個 role agent，各有獨立
prompt / model / tools / context view，協作契約顯性化，達到:關注點分離、可獨立單測、
改一處只動一個 agent、為 memory / feedback / Supervisor 鋪好插槽。

**非目標（Phase 0）**:不加 memory 寫入、不建 feedback channel、不動監控平面、不改任何可觀察行為。

---

## 2. Shared State（協作的地板 — 先定資料，再定 agent）

三個 agent **只透過 shared state 溝通**（不做 agent-to-agent 對話）。Phase 0 沿用現有
`GraphState`，這裡是把「協作會用到的欄位」顯性化成契約:

```python
BuildState = {
    # ── 意圖與計畫 ────────────────────────────────────────────
    "instruction": str,              # 原始 user 需求（Repair 三路輸入之一）
    "phases": list[Phase],           # Planner 的產出（見 §4.1）
    "current_phase_idx": int,

    # ── 畫布與執行 ────────────────────────────────────────────
    "canvas": PipelineJSON,          # nodes + edges（Builder 的工作對象）
    "exec_trace": dict,              # 各 node 的 runtime snapshot（schema+sample rows）

    # ── 協作訊號（Phase 0 新增欄位,由 graph 寫,LLM 不碰） ──
    "handoff": {                     # Builder→Planner 的觸發（§5.3）
        "kind": "PHASE_DONE|STUCK|INFEASIBLE|AMBIGUOUS",
        "phase_id": str,
        "detail": str,               # verifier reason / 缺口描述
    } | None,
    "planner_verdict": {             # Planner 的裁決（§5.4;Phase 2 起才有語意裁判）
        "verdict": "APPROVE|REVISE|REPLAN",
        "phase_id": str,
        "feedback": str,             # REVISE 時給 Builder 的一句話
    } | None,
    "repair_ticket": {               # Repair 的接手單（§6;Phase 2 起才有 post-delivery）
        "source": "in_build|post_delivery",
        "feedback": str,             # user 原話 or 裁判 reject 理由
        "diagnosis": "build_level|plan_level" | None,
    } | None,

    # ── 預算計數（graph 管理,防繞圈） ─────────────────────────
    "budgets": {"react_rounds": int, "revise_attempts": int,
                "replan_count": int, "repair_iterations": int},
}
```

```python
Phase = {
    "id": str,                # p1, p2…
    "goal": str,              # 意圖一句話（禁 block 名 — 現有 goal_plan 規則不變）
    "expected": str,          # raw_data|transform|verdict|chart|table|scalar|alarm
    "expected_output": str,   # 產出「語意」描述 — Planner 語意裁判的判準
    "constraints": list[str], # 硬限制（時間窗、機台、禁用做法…）
    "why": str,
}
```
> 與現行 `goal_plan` 產出的 phase 幾乎同形（id/goal/expected/why 已存在）;
> Phase 0 只需補 `expected_output` 與 `constraints` 欄（可先空,不改行為）。

---

## 3. Agent 的組成元素與介面

### 3.1 十一個元素（現有 LangGraph 直接餵）

| # | 元素 | 現 LangGraph 來源 | Phase 0 |
|---|---|---|---|
| 1 | Charter 憲章 | 各 node system prompt 開頭段 | 收攏 |
| 2 | System prompt | 各 node 的 prompt 組裝函式 | 收攏 |
| 3 | Model cfg | `get_llm_client()` + settings | 收攏 |
| 4 | Tools（allowed） | node 內宣告的 tools 列表 | 收攏 |
| 5 | State view（in） | `_build_observation_md` / `_build_canvas_diff_md` | 收攏 |
| 6 | Output patch（out） | `GraphState` reducers | 收攏 |
| 7 | Budgets | `MAX_REACT_ROUNDS=32`/`MAX_REVISE=1`/`recursion_limit=60` | 收攏 |
| 8 | 協作協定 | graph conditional edges | 顯性化為 §2 的 handoff/verdict 欄位 |
| 9 | Memory hooks（read） | — | **空介面**（Phase 3 填） |
| 10 | Record hooks（write） | — | **空介面**（Phase 4 填,對應 B 表觸發） |
| 11 | Trace emit | `BuildTracer` | **空介面**（Phase 2 擴成 Episode） |

### 3.2 介面簽名（Phase 0 落地形狀）

```python
# python_ai_sidecar/agent_builder/agents/base.py
class RoleAgent(Protocol):
    name: str                                  # "planner" | "builder" | "repair"
    charter: str                               # 元素1
    def system_prompt(self, view) -> str: ...  # 元素2（可含 cache_control 斷點）
    model_cfg: ModelCfg                        # 元素3 {model, effort, cache}
    allowed_tools: list[ToolSpec]              # 元素4
    def state_view(self, state: BuildState) -> View: ...     # 元素5（compact！）
    async def run(self, view: View) -> StatePatch: ...       # 元素6（LLM 呼叫在此）
    budgets: Budgets                           # 元素7
    # ── 插槽（Phase 0 為 no-op,之後 phase 填內容,不再改骨） ──
    def memory_query(self, view) -> list[MemoryHit]: ...     # 元素9  (Phase 3)
    def record_triggers(self) -> list[RecordRule]: ...       # 元素10 (Phase 4)
    def trace_fields(self, view, patch) -> dict: ...         # 元素11 (Phase 2)
```

```python
# python_ai_sidecar/agent_builder/agents/registry.py — 單一事實來源
AGENTS = {
  "planner": PlannerAgent(model_cfg=GLM_MEDIUM, tools=[...], budgets=...),
  "builder": BuilderAgent(model_cfg=GLM_MEDIUM, tools=CANVAS_OPS+INSPECT, budgets=...),
  "repair":  RepairAgent(model_cfg=GLM_MEDIUM, tools=CANVAS_OPS+DIFF, budgets=...),
}
# 未來 tier-router = 改這裡的 model_cfg,一行的事
```

**graph node 變薄**:node 函式只做「取 agent → state_view → run → apply patch → 寫 handoff 欄位」。
路由仍 100% 在 graph 的 conditional edges（flow-in-graph 不變）。

### 3.3 檔案佈局（Phase 0 新增）

```
python_ai_sidecar/agent_builder/agents/
    base.py        # RoleAgent 協定 + View/StatePatch/Budgets 型別
    planner.py     # PlannerAgent（吃現 goal_plan 的 prompt+邏輯）
    builder.py     # BuilderAgent（吃現 agentic_phase_loop）
    repair.py      # RepairAgent（吃現 phase_revise）
    registry.py    # AGENTS 單一事實來源
graph_build/graph.py           # node 改薄,edges 不變
graph_build/nodes/*.py         # 邏輯搬到 agents/ 後留薄 wrapper（或漸進刪除）
```

---

## 4. Planner：規劃 + 裁判

### 4.1 產出契約
Planner 吃 `instruction`（+ Phase 3 起:preference/presentation/domain memory），
產出 `phases: list[Phase]`（§2 schema）。**一個 phase = 一個可獨立驗收的意圖單位**;
`expected_output` 必須寫到「裁判可以拿它判對錯」的具體度（例:「每小時 OOC 件數的長條圖,
x=小時、y=count」,而非「一張圖」）。

### 4.2 語意裁判（Phase 2+ 行為;Phase 0 定介面）
- **輸入**:`phase.expected_output` + 該 phase 產出節點的 runtime snapshot（columns + 3 sample rows,
  從 `exec_trace` 取,**不重展全 context**）。
- **判準**（prompt 骨架,principle 不列 case）:
  1. 產出的「種類」= expected?（chart vs table vs scalar — 結構層 Verifier 已擋,裁判複核語意）
  2. 產出的「內容」覆蓋 expected_output 的語意?（對的欄位、對的聚合、對的範圍）
  3. constraints 有沒有被違反?
- **輸出**:`planner_verdict`（APPROVE / REVISE+feedback / REPLAN）。
- **預算**:同一 phase 最多 REVISE 2 次;REPLAN 全 build 最多 2 次 → 超過升級 Repair（in_build）。
  數字由 graph 的 `budgets` 管,不寫在 prompt。

### 4.3 REPLAN 的執行語意
REPLAN 只重排**受影響的 phase**（該 phase 及其下游）;已 APPROVE 的上游 phase 與其 canvas 節點保留。
graph 依 `phases[].id` diff 決定重跑範圍 — deterministic,不靠 LLM 判斷「哪些要重跑」。

---

## 5. Planner ↔ Builder 協作協定

### 5.1 交接
Planner 產 phases → confirm gate（現有,user 可改）→ Builder **一次吃一個 phase**。
Builder 的 view = 當前 phase + canvas + exec_trace + matching blocks（現有 observation 邏輯,重用不重造）。

### 5.2 兩層 review
| 層 | 誰 | 檢什麼 | 時機 | Phase |
|---|---|---|---|---|
| L1 結構 | Verifier（deterministic node） | covers/orphan/leaf/validation | 每 phase,便宜 | **已有** |
| L2 語意 | Planner 裁判 | expected_output 語意符合度 | L1 過後 | **Phase 2+** |

### 5.3 Builder→Planner 觸發（graph 偵測,非 LLM 自由意志）

| 觸發 | Deterministic 偵測條件 | Planner 反應 |
|---|---|---|
| **PHASE_DONE** | L1 verifier ADVANCE | L2 語意裁判 |
| **STUCK** | react_rounds 用盡 或 stuck-detector（連續同動作）命中 | 判斷 plan 問題 or 執行問題 → REVISE/REPLAN/升級 |
| **INFEASIBLE** | matching blocks 為空 或 反覆 covers-mismatch ≥ N | REPLAN 或標記能力缺口（→未來 doc 備忘/新 block 需求） |
| **AMBIGUOUS** | Builder 對必填參數在 plan+constraints 找不到依據（現行 pre_clarify 邏輯的 phase 版） | 補 constraints 後重入 |

### 5.4 時序（目標態;Phase 0 = 只有 L1 + Builder 自省）
```
Planner ──phases──▶ confirm gate ──▶ Builder(p1)
  Builder ReAct → L1 Verifier ✓ → handoff=PHASE_DONE
  Planner L2 裁判:
    APPROVE → Builder(p2)…
    REVISE(feedback) → Builder 同 phase 再修（≤2 次）
    REPLAN → Planner 改 phases → 只重跑受影響 phase
  STUCK/INFEASIBLE/AMBIGUOUS → Planner 裁決;預算盡 → repair_ticket(in_build)
全 phase APPROVE → finalize → 交付 user
```

---

## 6. Repair：feedback 驅動的修正者

### 6.1 觸發（不 auto-chain）
| 觸發 | 條件 | Phase |
|---|---|---|
| **in_build** | Planner 裁決預算用盡（REVISE×2 + REPLAN×2 仍不過） | Phase 2+ |
| **post_delivery** | user 在對話視窗給負向 feedback（feedback channel,C#1） | Phase 2+ |

> 澄清:Builder 內建 `phase_revise` 自省（round 用盡的 1 次重試）**不是 Repair** —— 那是
> Builder 自癒。RepairAgent 是跨 Planner/Builder、根因級、feedback 驅動。
> Phase 0:RepairAgent 先承接 phase_revise 的自省邏輯（行為不變）,§6.2-6.4 介面先定。

### 6.2 三路輸入
`instruction`（原話）+ 現 pipeline（canvas + exec_trace + 最後執行結果）+ `repair_ticket.feedback`。

### 6.3 診斷（Repair 的核心推理,輸出寫回 repair_ticket.diagnosis）
| 判準（依序檢查） | 診斷 | 動作 |
|---|---|---|
| feedback 指向呈現/參數/單一 block（「圖種錯」「排序不對」「範圍錯」） | **build_level** | direct-patch |
| feedback 指向意圖/結構（「我要的不是這個」「少了 X 分析」「應該按 Y 分組」） | **plan_level** | re-plan |
| 無法判定 | 問 user 一個二選一（走既有 clarify 卡機制） | — |

### 6.4 執行
- **direct-patch**:canvas ops（add/connect/set_param/remove）動最小範圍 → 重跑 L1 →（Phase 2+）L2 → 交付。
- **re-plan**:產修正 phases diff → **交回 Planner confirm**（Planner 仍是 plan 的 owner）→
  依 §4.3 只重跑受影響 phase → 交付。
- 預算:`repair_iterations ≤ 3`（graph 管）;超過 → 明確告訴 user 需要人工接手（不無限修）。
- 學習（Phase 4+）:定位的根因寫 `correction`（tag=plan|execute）。

---

## 7. Graph 拓撲

### Phase 0（= 現行拓撲,node 換薄殼,行為不變）
```
goal_plan(PlannerAgent) → confirm_gate → agentic_phase_loop(BuilderAgent)
  ⇄ phase_verifier(deterministic) → …all phases… → finalize
  agentic_phase_loop --stuck--> phase_revise(RepairAgent 承接) --retry/handover-->
```

### 目標態（Phase 2+,新增邊以虛線表示）
```
goal_plan ─▶ confirm ─▶ builder_loop ⇄ verifier(L1)
                             │ PHASE_DONE
                             ▼
                      planner_judge(L2) ─APPROVE─▶ next phase / finalize ─▶ 交付
                             │ REVISE ─▶ builder_loop（同 phase）
                             │ REPLAN ─▶ goal_plan(局部)
   repair_entry ◀─ in_build（預算盡）
   repair_entry ◀─ post_delivery feedback（C#1 channel）
   repair_entry ─diagnose─▶ direct_patch ─▶ verifier ─▶ 交付
                └─────────▶ re_plan ─▶ goal_plan(局部)
```
所有新邊 = conditional edges 讀 §2 的 handoff/verdict/ticket 欄位 — **仍是 flow-in-graph**。

---

## 8. Step-by-Step Execution Plan（Phase 0）

每步一個小 PR,**SLASH-17 當回歸閘**（strict 品質 / 成本 / cache 命中 40-58% 三項齊看）。

| Step | 內容 | 驗收 |
|---|---|---|
| 1 | `agents/base.py` + `registry.py` 骨架 + View/Patch 型別 + 空插槽（元素 9-11） | 單測:契約型別;不接線 |
| 2 | `BuildState` 補 `handoff`/`planner_verdict`/`repair_ticket`/`budgets` 欄（先無人寫入） | SLASH-17 零回歸 |
| 3 | `goal_plan` → `PlannerAgent`（Phase schema 補 expected_output/constraints 欄,先允許空） | SLASH-17;cache 驗證 |
| 4 | `agentic_phase_loop` → `BuilderAgent` | SLASH-17;cache 驗證 |
| 5 | `phase_revise` → `RepairAgent`（含 §6 介面,行為=原自省） | SLASH-17 |
| 6 | config 收攏 registry;刪散落常數;nodes/*.py 變薄 wrapper | SLASH-17 全綠 + code review |

**單測要求**（每 agent）:`state_view` 給定 state → view 快照測試;`run` 用 mock LLM →
patch 形狀測試;budgets 邊界測試。graph 路由函式維持現有 pure-function 測試。

---

## 9. Edge Cases & Risks

- **Prompt-cache prefix**:拆 prompt 改變 cache 斷點 → 每步驗 `cache_read` 仍 40-58%,退步就不 merge。
- **Token**:view 必須沿用 compact 邏輯（round-1 全量、round-2+ delta、32 訊息上限）;
  L2 裁判只吃 snapshot（columns+3 rows）,嚴禁重展全 context。
- **介面穩定性**:元素 9-11 + §5.3/§6.3 是後面 phase 的地基,**是本 spec 最需要 review 的部分**。
- **守則**:不可退回 supervisor-LLM;Verifier 不 agent 化;判準寫 principle 不列 case;
  預算數字在 graph 不在 prompt。
- **v27 legacy path** 不動;**驗收 = 零回歸**。

---

## 10. Roadmap

| Phase | 內容 | 打開本文哪一段 |
|---|---|---|
| **0** | 3-agent 骨架 + 契約 + registry（零行為改變） | §2/§3/§8 |
| **1** | 監控平面:4 monitor agent 當 requester 接 Planner（canned vs dynamic 屆時拍板） | — |
| **2** | Episode/feedback channel + divergence → 開 L2 裁判、REPLAN、repair_ticket 兩觸發 | §4.2/§5.4/§6.1 |
| 3 | agent_knowledge `class` 欄 + `block_doc_memos` 表 → 填元素 9 | §3.1 |
| 4 | 三 agent record hooks（B 表觸發）→ 填元素 10 | §3.1 |
| 5 | Supervisor 蒸餾 + curation → 吃元素 11 的 Episode | — |

---

---

## 11. 驗收條款（Acceptance Checklist）— 2026-07-02 交付實測

> 流程改進（user 回饋）:自下個 phase 起,驗收條款在 spec 簽核時就先議定。

| # | 條款 | 交付實測結果 | user 自行驗證方式 |
|---|---|---|---|
| A1 | 3 個 role agent 存在且註冊 | planner / builder / repair | `python -c "from python_ai_sidecar.agent_builder.agents import registered_names; print(registered_names())"` |
| A2 | graph 3 個 node 走 agent 委派,edges 不變 | graph.py `_planner/_builder/_repair_delegate` | 看 `graph_build/graph.py` v30 區塊 |
| A3 | budgets 單一來源（值不變 32/1） | nodes 讀 agents 的 Budgets | 契約單測 `test_budgets_are_single_source_with_nodes` |
| A4 | 契約單測全綠 | 13/13 passed | `pytest python_ai_sidecar/tests/test_agents_contract.py -q` |
| A5 | 既有測試零新增失敗 | 381 passed；3 fail 為改動前既存（stash 驗證） | `pytest python_ai_sidecar/tests/ -q --ignore=...test_prompt_size.py` |
| A6 | **SLASH-17 品質零回歸** | **strict 17/17 MATCH**（baseline ~14,GLM 變異 12-15） | EC2 `grade_strict.py p0_gate` |
| A7 | 速度零回歸 | 22.3 min（baseline 28 min） | `/tmp/s17_p0_gate.log` |
| A8 | **cache 命中 40-58% 不退** | **54.7%** | trace 聚合（llm_calls cache_read） |
| A9 | 空插槽介面就位（元素 9-11） | memory_query / record_triggers / trace_fields no-op | `agents/base.py` |
| A10 | ma_* 協作欄位就位（無 writer） | initial_state 5 欄全數就位 | 單測 `test_initial_state_has_collab_fields` |

**Phase 0 明確未做（依界線）**:語意裁判 / REPLAN / repair ticket 的行為（Phase 2+）;
prompt 全文搬入 agents（漸進）;監控平面（Phase 1）。

Commits: `36042b8f`（Steps 1-2）+ `9440c0fd`（Steps 3-5 + 委派）。
