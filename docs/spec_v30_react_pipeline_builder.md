# v30 — Goal-Oriented ReAct Pipeline Builder (Spec)

> 2026-05-16 — 取代現行 v16 macro_plan + compile_chunk × N 架構。基於 ReAct 模型：
> 語意層 phase plan + 每 phase 內 observe → reason → act → check loop。

## Context & Objective

### 現行 v27 架構的根本問題

1. **macro_plan 在未見任何資料時就決定 block 順序** → 等於要 LLM 想像資料 shape，幻覺率高
2. **bullets 是「沒有結構化 planning」的 workaround** → user feedback 被翻譯丟、補 C 規則 deterministic 救
3. **block description 散落、語意/usage 分離** → LLM 看 description 推測，常選錯 block
4. **失敗時 silent finish 或 cascade fail** → user 不知道做完沒，build_traces 也難分辨
5. **canvas 漸進建構不被尊重** → 強制 `is_from_scratch=True` 重做整條
6. **frontend canvas 的 preview snapshot 沒傳給 backend agent** → 即使 user 已拉 nodes，agent 也是「半盲」

### v30 目標

- **Goal-oriented planning**：plan 描述「要達到什麼狀態」，不指定 block
- **Agentic execution per phase**：每 phase 內 ReAct loop，邊看真實資料邊決定下一步
- **Honest failure**：失敗時 halt + handover，給 user 具體可動的選項
- **Schema-rich block doc + runtime per-node schema**：讓 LLM 看到的資料說明完整且 usage-oriented
- **Build Traces 完整 capture**：phase / round / action / observation 都進 trace，admin viewer 可重現

---

## Architecture & Design

### 1. Graph 流程

```
                  ┌─────────────────────────┐
                  │ user prompt + canvas    │
                  └────────────┬────────────┘
                               ▼
                  ┌─────────────────────────┐
                  │ goal_plan_node          │  (LLM call 1)
                  │  - 讀 instruction       │
                  │  - 讀 canvas snapshot   │
                  │  - LLM 可呼叫 inspect_  │
                  │    catalog 看 block 大綱 │
                  │  - emit phases JSON     │
                  └────────────┬────────────┘
                               ▼
                  ┌─────────────────────────┐
                  │ goal_plan_confirm_gate  │  (interrupt + user UI)
                  │  - SSE: goal_plan_      │
                  │    proposed             │
                  │  - user 編輯/確認 phases │
                  └────────────┬────────────┘
                               ▼
        ┌──────────────────────────────────────────────┐
        │ for phase in phases:                          │
        │                                               │
        │   ┌─────────────────────────────────────┐    │
        │   │ phase_init                          │    │
        │   │  SSE: phase_started                 │    │
        │   └────────────┬────────────────────────┘    │
        │                ▼                              │
        │   ┌─────────────────────────────────────┐    │
        │   │ react_round (max 8 rounds/phase)    │    │
        │   │  observe (build prompt with         │    │
        │   │    AVAILABLE INPUTS + phase goal)   │    │
        │   │  LLM tool-use:                      │    │
        │   │    - inspect_node_output(nid)       │    │
        │   │    - inspect_block_doc(block_id)    │    │
        │   │    - add_node / connect / set_param │    │
        │   │    - remove_node                    │    │
        │   │    - phase_complete(rationale)      │    │
        │   │  auto-preview after add/connect/set │    │
        │   │  SSE: phase_round, phase_action,    │    │
        │   │       phase_observation             │    │
        │   └────────────┬────────────────────────┘    │
        │                ▼                              │
        │   ┌─────────────────────────────────────┐    │
        │   │ check_phase_done (deterministic)    │    │
        │   │  - 比對 expected_kind vs 實際 output│    │
        │   │  - 滿足 → next phase                │    │
        │   │  - 不滿足 → 回 react_round 繼續     │    │
        │   │  - max round 到 → phase_revise      │    │
        │   └─────────────────────────────────────┘    │
        │                                               │
        │   ┌─────────────────────────────────────┐    │
        │   │ phase_revise (only if max round 到) │    │
        │   │  - LLM 自我反思 + 換策略 1 次       │    │
        │   │  - 若仍失敗 → halt_handover         │    │
        │   └─────────────────────────────────────┘    │
        └──────────────────────────────────────────────┘
                               ▼
                  ┌─────────────────────────┐
                  │ halt_handover (if any   │
                  │ phase failed)           │
                  │  - SSE: phase_failed    │
                  │  - SSE: handover_pending│
                  │  - 4 options for user   │
                  └────────────┬────────────┘
                               ▼
                  ┌─────────────────────────┐
                  │ finalize_node (existing)│
                  │  - validate, dry_run,   │
                  │    layout               │
                  │  - SSE: build_done      │
                  └─────────────────────────┘
```

### 2. Block Description 標準格式 (Concern 1)

**Source 類強制**完整 schema 表格 + 每 col 4 區塊 (type / what / usage / anti-usage)。

範本 (`block_process_history`)：

```markdown
== Output Schema (8 cols, deterministic) ==

┌─────────────────────────────────────────────────────────────────┐
│ col: spc_status                                                 │
│ type: enum["PASS"|"OOC"]                                        │
│ what: 此 event 整體 SPC 是否有任一 chart OOC (event-level rollup) │
│ usage:                                                          │
│   [best] 「這 event 有沒有 OOC?」→ 直接讀此欄                      │
│   [best] 「過去 N 天有 OOC 的 events」→ filter(spc_status=='OOC') │
│   [no] 「具體哪張 chart OOC?」→ 用 spc_summary.ooc_chart_names  │
│   [no] 「OOC 數量?」→ 用 spc_summary.ooc_count                  │
│   [warn] string 'OOC' 不是 boolean，filter value 加引號            │
└─────────────────────────────────────────────────────────────────┘
```

每 col 4 區塊：
- **type**：精確型別，含 enum/list/dict 結構
- **what**：欄位語意（這欄代表什麼）
- **usage**：[best] 最佳路徑 / [ok] 可用 / [no] 別用此欄做這件事 / [warn] 雷區
- **anti-usage**：明確列「這欄不適合答的問題」+ 指向正確欄位

**Transform / output 類**：cols 隨上游變，用 `Output rule` 描述 + runtime injected schema 補真實值。

### 3. Runtime Per-Node Schema (Concern 2)

**目的**：每執行 1 個 node，產生**該 node 這次跑出來的完整 schema doc**，注入下個 LLM call 的 `AVAILABLE INPUTS` 段。

**Helper**：`infer_runtime_schema(df, block_spec) → markdown`

範例輸出 (n1 跑完後)：

```markdown
n1 [block_process_history] params={tool_id:"EQP-01", time_range:"7d"}
   → 47 rows × 8 cols

Schema (this run, semantics merged from block doc):

┌─────────────────────┬──────────────────────────┬─────────────────────────────┐
│ col                 │ inferred type            │ usage hint (from doc)       │
├─────────────────────┼──────────────────────────┼─────────────────────────────┤
│ eventTime           │ string (ISO 8601)        │ 排序/時間 filter/chart x   │
│ toolID              │ string [unique:1]        │ 此 run 只 EQP-01           │
│ lotID               │ string [unique:34]       │ 多 lot 可分色              │
│ step                │ string [unique:1]        │ 此 run 只 STEP_001         │
│ spc_status          │ enum[PASS=39, OOC=8]     │ [best] 直接判 event 有否 OOC   │
│ fdc_classification  │ string|null [3 distinct] │ FDC 分類；非 null = fault │
│ spc_charts          │ list[6-dict] × 12        │ 要單一 chart trend 才 unnest│
│ spc_summary         │ dict{ooc_count, total_   │ [best] ooc_count 已預算       │
│                     │   charts, ooc_chart_names}│   (省 unnest+count)       │
└─────────────────────┴──────────────────────────┴─────────────────────────────┘

Sample (2 rows):
[
  {"eventTime":"2026-05-15T08:36:31","toolID":"EQP-01","lotID":"LOT-0541",
   "step":"STEP_001","spc_status":"OOC","fdc_classification":null,
   "spc_charts":[/* 12 dicts */],
   "spc_summary":{"ooc_count":1,"total_charts":12,"ooc_chart_names":["r_chart"]}},
  {"eventTime":"2026-05-15T07:22:14","toolID":"EQP-01","lotID":"LOT-0540",
   "step":"STEP_001","spc_status":"PASS",...}
]
```

**Token budget per node**: ≤ 1.5 KB (8 col schema + 2 row sample)。  
**Cap**: 5 個 node 同時 inject = ~7.5 KB。  
**Injection rule**: 只 inject 「**和當前 phase 直接相關**」的 nodes（依 phase 的 depends_on 走 + 永遠包含當前 phase 已建的 nodes）。

### 4. Goal Plan + User Edit Follow (Concern 3)

**bullets 廢除**。改用 Goal Plan card：

```json
{
  "phases": [
    {"id":"p1","goal":"撈 EQP-08 過去 7d process_history 資料",
     "expected":"raw_data","why":"先 7d 試，無資料退到 30d"},
    {"id":"p2","goal":"判斷該機台最後 OOC 時是否 ≥2 charts OOC",
     "expected":"verdict","why":"user 需要 alarm 條件"},
    {"id":"p3","goal":"展示該時刻所有 OOC 的 SPC charts",
     "expected":"chart","why":"user 字面說 'SPC Panel 分別列出'"}
  ],
  "alarm": null
}
```

`expected` 是 phase completion 的粗類別：
- `raw_data` — terminal node 是 source / 一般 dataframe
- `transform` — 中繼 dataframe
- `verdict` — 終端 block 是 verdict-shaped（block_step_check 等）
- `chart` — 終端 block 在 chart category
- `table` — 終端 block 是 block_data_view
- `scalar` — 終端 1×1 結果
- `alarm` — 觸發 alert 機制

**Frontend Goal Plan card**:
```
   ┌────────────────────────────────────────┐
   │ [goal] Build Plan (3 phases)                │
   ├────────────────────────────────────────┤
   │ □ p1: 撈 EQP-08 過去 7d process_history │
   │      [編輯] [刪除]                      │
   │ □ p2: 判斷最後 OOC 時是否 ≥2 charts OOC │
   │      [編輯] [刪除]                      │
   │ □ p3: 展示該時刻所有 OOC SPC charts    │
   │      [編輯] [刪除]                      │
   │ + 新增 phase                            │
   ├────────────────────────────────────────┤
   │     [Confirm & Build]                   │
   └────────────────────────────────────────┘
```

User edit/delete/add → frontend POST 完整 phases。Backend `goal_plan_node` 收到 user 版本後**完全 replace**（不能再 LLM 改寫）。

**確保 follow** 機制：每 phase 進入 react_round 時，prompt 強制重述：
```
== CURRENT PHASE (用戶確認過的目標，不要偏離) ==
goal: 判斷該機台最後 OOC 時是否 ≥2 charts OOC
expected: verdict
why: user 需要 alarm 條件
```

trace 記錄：「phase p2 user-edited from 'X' → 'Y'，按 Y 執行」。

### 5. Failure → Halt + Handover (Concern 4)

**絕不 silent skip**。當 react_round 跑滿 max（=8）+ phase_revise 也失敗：

```
   [warn] Phase 2「判斷該機台最後 OOC 時是否 ≥2 charts OOC」做不到

   嘗試紀錄:
   • Round 1-3: 試 block_step_check 讀 spc_summary.ooc_count
                結果：read OK 但找不到「最後 OOC 時」的 row 篩選方式
   • Round 4-6: 試 unnest+filter+groupby+sort+step_check 5 步路徑
                結果：cross-branch ref 卡 (n4 → n5 沒 eventTime)
   • Round 7-8: 試 block_join 把 step 5 的 last time join 回 step 3
                結果：join 在 self-source 配對失敗

   缺乏的能力:
   - 沒有 「last-row context filter」 一步到位的 block
   - block_join self-join 不支援 cross-branch keyed reduce

   進度保留:
   (done) Phase 1 完成 — n1=block_process_history 建好 (47 rows on canvas)
   (fail) Phase 2 失敗
   ⏸ Phase 3 暫停 (依賴 Phase 2)

   請選下一步：

   [[edit] 改寫 phase 2 目標]   讓你重述要怎麼判，agent 用新目標再試
   [[handover] 我自己接手]          結束 agent session，canvas 給你手動繼續
   [[backlog] 補一個 follow-up]    把缺乏的能力記成 backlog，agent 升級後 retry
   [(fail) 中止]                 全部清掉，重新開始
```

3 個關鍵原則：
1. **絕不 silent skip**：phase 失敗一定停下等 user
2. **誠實說缺什麼**：不只「失敗」，列出具體 round 紀錄 + 缺乏的能力
3. **保留進度**：canvas 上 phase 1 nodes 留著，user 接手有起點

**Capability backlog (option 3)**：YAGNI，v30 POC 暫不做。先讓 user 接手或中止。

### 6. Build Traces 設計

**現有 trace 結構**：`{graph_steps[], llm_calls[], final_pipeline, ...}`  
**v30 新增**：

```json
{
  // existing fields preserved
  "v30_phases": [
    {
      "id": "p1",
      "goal": "撈 EQP-08 過去 7d process_history 資料",
      "expected": "raw_data",
      "user_edited": false,
      "user_edit_history": null,  // or [{from, to, ts}]
      "started_at": "2026-05-16T10:00:00Z",
      "completed_at": "2026-05-16T10:00:08Z",
      "rounds": [
        {
          "round_idx": 1,
          "ts": "2026-05-16T10:00:01Z",
          "observation_md": "...full AVAILABLE INPUTS + phase goal markdown injected to LLM...",
          "llm_call_id": "llm_call_3",  // ref into top-level llm_calls[]
          "actions": [
            {"type": "add_node", "block_id": "block_process_history",
             "params": {"tool_id":"EQP-08","time_range":"7d"},
             "result": {"node_id":"n1","status":"ok"}, "ts": "..."},
            {"type": "auto_preview", "node_id": "n1",
             "result": {"rows": 47, "schema_md": "...runtime schema..."}, "ts": "..."}
          ]
        },
        {
          "round_idx": 2,
          "ts": "...",
          "observation_md": "...",
          "llm_call_id": "llm_call_4",
          "actions": [
            {"type": "phase_complete", "rationale": "process_history 47 rows OK"}
          ]
        }
      ],
      "outcome": {
        "status": "completed",
        "verifier_check": {"expected": "raw_data", "got": "47 rows × 8 cols", "match": true}
      }
    },
    {
      "id": "p2",
      "goal": "判斷該機台最後 OOC 時是否 ≥2 charts OOC",
      ...
      "outcome": {
        "status": "failed",
        "verifier_check": null,
        "fail_reason": "max_rounds_with_no_progress",
        "missing_capabilities": [
          "last-row context filter as single block",
          "block_join cross-branch keyed reduce"
        ]
      }
    }
  ],
  "v30_handover": {
    "triggered_at": "2026-05-16T10:02:30Z",
    "failed_phase_id": "p2",
    "options_offered": ["edit_goal","take_over","backlog","abort"],
    "user_choice": "take_over",  // or null if still pending
    "user_choice_at": "2026-05-16T10:03:15Z"
  }
}
```

**Admin viewer 改動** (`/admin/build-traces/<id>`)：

```
┌─────────────────────────────────────────────────────────────────┐
│ Trace 20260516-100000-abc                                       │
│ status: failed_handover  duration: 3min 15s                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ [goal] Goal Plan (3 phases, 0 user edits)                          │
│   (done) p1: 撈 EQP-08 過去 7d process_history 資料  (8s, 2 rounds) │
│   (fail) p2: 判斷該機台最後 OOC 時是否 ≥2 charts OOC (2m 22s, 8 rds)│
│   ⏸ p3: 展示該時刻所有 OOC SPC charts (skipped - p2 失敗)      │
│                                                                 │
│ ▶ Phase 1 Detail [click to expand]                              │
│ ▼ Phase 2 Detail                                                │
│   Round 1 [llm_call_3] (12s)                                    │
│     Observation:                                                │
│       AVAILABLE INPUTS:                                         │
│         n1 [block_process_history] 47 rows × 8 cols             │
│         schema: spc_status enum, spc_summary dict {ooc_count}.. │
│         sample rows: [...]                                      │
│       PHASE GOAL: 判斷...                                        │
│     Actions:                                                    │
│       • inspect_node_output(n1, n_rows=2) → returned 2 rows     │
│       • add_node(block_step_check, params={...})                │
│       • auto_preview → result: {rows:1, pass:false, value:1}    │
│   Round 2 [llm_call_4] (15s)                                    │
│     ...                                                         │
│   Round 8 [llm_call_10] (18s)                                   │
│     Action: phase_revise triggered                              │
│   Phase Revise Round (24s)                                      │
│     LLM self-reflection: ...                                    │
│     Tried alternative: ...                                      │
│   Outcome: failed                                               │
│     fail_reason: max_rounds_with_no_progress                    │
│     missing_capabilities: [...2 items...]                       │
│                                                                 │
│ [handover] Handover [user chose: take_over at 10:03:15]                │
│   Options offered: edit_goal / take_over / backlog / abort      │
│   Canvas state at handover: 1 node (n1)                         │
│                                                                 │
│ ▶ Final Pipeline (1 node from p1)                               │
│ ▶ All LLM calls (10 calls)                                      │
└─────────────────────────────────────────────────────────────────┘
```

**Trace SSE events** (real-time stream)：

| SSE Event | When | Frontend reaction |
|---|---|---|
| `goal_plan_proposed` | After goal_plan_node | Render Goal Plan card |
| `goal_plan_confirmed` | User confirms | Card collapse, timeline appears |
| `phase_started:p1` | Enter phase | Highlight p1 as in-progress (blue spinner) |
| `phase_round:p1 round=2/8` | Each ReAct round | Show "round 2/8" subtitle |
| `phase_action:p1 type=add_node block=X` | LLM tool call | Toast "+ block_X" |
| `phase_action:p1 type=auto_preview node=n1 rows=47` | Auto preview | Toast "n1 → 47 rows" |
| `phase_observation:p1 schema_md=...` | LLM sees data | (optional UI: "agent observed n1 schema") |
| `phase_completed:p1` | Verifier OK | p1 → green (done), p2 highlights |
| `phase_revise_started:p2` | Max round | p2 → yellow with "revising strategy..." |
| `phase_failed:p2 reason=...` | Revise also fails | p2 → red (fail) |
| `handover_pending` | Halt | Modal opens |
| `handover_chosen choice=take_over` | User picks | Modal closes, banner |
| `build_done status=...` | Final | Top banner (green/yellow/red) |

---

## Step-by-Step Execution Plan

### Phase A — Backend POC (5-7 天)

1. **Block description 改造** (1 天)
   - 新格式 schema box for `block_process_history` (POC 只動這 1 個 source)
   - Helper `format_col_box(col_meta) → markdown` 統一渲染
   - `seed.py` 對應改動

2. **Runtime schema generator** (1 天)
   - `infer_runtime_schema(df, block_spec) → markdown` in `pipeline_builder/schema_inference.py`
   - 推斷邏輯：unique count, enum extraction, nested shape
   - Cap: 30 cols, 2 sample rows, value truncation
   - Wired into executor `_preview_output` path → 存進 `exec_trace[lid].runtime_schema_md`

3. **新 graph nodes** (3 天)
   - `goal_plan_node`：替代 macro_plan，emit phases JSON
   - `goal_plan_confirm_gate`：interrupt + user UI handshake
   - `agentic_phase_loop`：實作 ReAct round 機制
     - `_build_phase_observation_md(state)` 組裝 AVAILABLE INPUTS
     - LangGraph state field: `phases`, `current_phase_idx`, `phase_round`, `phase_outcomes`, `handover`
   - `phase_revise_node`：max round 後的 self-reflection
   - `halt_handover_node`：emit handover SSE，等 user 選

4. **新 tools** (1 天)
   - `inspect_node_output(node_id, n_rows=2)` (cap n_rows ≤ 3)
   - `inspect_block_doc(block_id)` (return full block description)
   - `phase_complete(rationale)` (terminal action of a phase)
   - 在 `BuilderToolset` 擴

5. **SSE events + tracer** (1 天)
   - 11 種新 events 加入 event_wrapper
   - Tracer 結構擴 `v30_phases[]` + `v30_handover`
   - 確保 admin trace JSON 完整含 round/action/observation

### Phase B — Frontend (3-5 天)

1. **Goal Plan card** (1.5 天)
   - 新元件 `GoalPlanCard.tsx`
   - Read-only display + Confirm 按鈕
   - SSE handler: `goal_plan_proposed`

2. **Phase Timeline** (1.5 天)
   - 元件 `PhaseTimeline.tsx`：5 種狀態 (pending / in-progress / completed / failed / paused)
   - SSE handler: `phase_started`, `phase_round`, `phase_action`, `phase_completed`, `phase_failed`
   - Per-phase round subtitle + action toast

3. **Handover Modal** (1 天)
   - 元件 `HandoverModal.tsx`：4 options
   - SSE handler: `handover_pending`
   - POST to `/agent/build/handover` endpoint

4. **Admin trace viewer 改動** (1 天)
   - `/admin/build-traces/<id>`：新 v30 phase timeline section
   - Per-round expandable showing observation_md + actions

### Phase C — Verify (1-2 天)

POC 驗證 5 case，每 case 跑 5 次：
- EQP-08 OOC ≥ 2 + show panel (user 原始 case)
- EQP-01 STEP_001 xbar trend (簡單 case)
- 跨機台 xbar 對照 (跨 branch case)
- APC drift 偵測 (連 N 次 + alarm)
- Recipe v1 vs v2 hypothesis test (兩 source union)

成功標準：
- ≥ 4/5 finished without handover
- 100% 沒有 silent failure (user 都看得到 phase 狀態)
- 每 build LLM call 數 ≤ 3× v27 baseline
- Build trace 完整可重現 phase × round × action

### Phase D — Phase edit + cutover (2-3 天)

1. Goal Plan card 加 edit/delete/add UI
2. Backend `goal_plan_node` 支援 user-supplied phases
3. POST `/agent/build/plan-edit` endpoint
4. 連續 7 天 chat builder 0 fallback → skill mode 也切 v30
5. v27 路徑保留 disabled state for emergency rollback

### Phase E — v27 retire (deferred)
- v30 連續 14 天穩定 + 0 critical bug → 刪 v16 macro+chunk code
- skill mode 跑通 + skill harness pass → 刪 v18 bullets

---

## Edge Cases & Risks

| Risk | 緩解 |
|---|---|
| LLM call 從 N → ~3N (cost 3×) | inspect_block_doc 結果 cache per session；phase_complete 早停減 round |
| Phase 卡住 LLM 不自我察覺 | deterministic stuck detector：(a) 同 op + 同 params 連 2 round (b) 連 3 round 純 inspect 無 add/connect |
| User 編輯 phase 後 LLM 偏離 | 每 round prompt 強制 inject `CURRENT PHASE (user-confirmed)`；trace 記錄 follow rate |
| 既有 saved skills 在 v30 跑壞 | skill mode 維持 v27 fallback 直到 v30 sign-off；migration 文件 |
| Frontend Phase Timeline 改動大 | Phase A backend 先穩，Phase B 分批；先 Goal Plan card → 再 Timeline → 再 Handover |
| Build trace 體積暴增 (per-round observation_md 大) | observation_md 用 reference (point to a observation snapshot file)；trace JSON 只存 ref id |
| inspect_node_output 被 LLM 濫用 (call 50 次) | cap 5 calls per round；超過自動 phase_revise |
| Goal Plan 描述太抽象 LLM 無法執行 | goal text 強制 ≥ 10 字 + 含至少 1 個動詞；prompt 範例教格式 |

---

## 4 Concern Cross-Check

| Concern | v30 解法 |
|---|---|
| **1. Node 說明完整 + 看資料機制** | ① 強制 4-block schema (type/what/usage/anti-usage) per col, source 類強制 ② Runtime per-node schema 自動產 + 注入 LLM ③ `inspect_node_output(n_rows≤3)` tool 主動查 |
| **2. 所有 input 可見 (含上游 output)** | 每 LLM call 強制 inject `AVAILABLE INPUTS`：pipeline declared inputs + trigger payload + **upstream nodes 的 runtime schema markdown** (含 type、what、usage、sample) |
| **3. Bullets 廢 + Goal Plan + user edit follow** | Bullets 下架；Goal Plan card user 可 edit/delete/add；backend 收 edited phases 後完全 replace；每 round prompt 強制重述 user-confirmed goal text |
| **4. 失敗處理 + 清楚進度** | Halt + Handover (絕不 silent skip)：列嘗試紀錄 + 缺乏的能力 + 4 options；11 SSE events 對應 frontend timeline 5 種視覺狀態 (pending/in-progress/completed/failed/paused) |

---

## Build Traces Cross-Check

| 重點 | Trace capture |
|---|---|
| 每個 phase 從哪到哪 | `v30_phases[i].started_at / completed_at / outcome.status` |
| 每 round LLM 看到什麼 | `v30_phases[i].rounds[j].observation_md` (full markdown) |
| 每 round LLM 做了什麼 | `v30_phases[i].rounds[j].actions[]` (tool call + result) |
| Auto-preview 後的真實 schema | `actions[].result.schema_md` (執行後產的 runtime schema) |
| User 編輯 phase 紀錄 | `v30_phases[i].user_edit_history[]` |
| Handover 觸發原因 + user 選擇 | `v30_handover.{failed_phase_id, options_offered, user_choice}` |
| Phase verifier check 結果 | `v30_phases[i].outcome.verifier_check` |
| 缺乏的 capability | `v30_phases[i].outcome.missing_capabilities[]` (for backlog) |

---

## 確認事項

請回覆「開始開發」後我啟動 Phase A POC（先做 1+2+3+4，5 SSE 事件最後）。

或如果有想再調整：
- 4-block schema 格式要不要再增減欄位
- Phase outcome 的 `expected` 7 種類別夠不夠
- Handover 的 4 options 要不要增減
- Trace 的 `observation_md` 要 inline 還是 by-reference
