# Todos

> 最後整理：2026-06-13。本檔追蹤 builder 準度/UX 的進行中工作 + backlog。
> Done 項目已進 git，這裡只留「為什麼 + 後續」的脈絡，細節看 commit。

---

## 0b. Chat 體感修正 + 協作式 Brief (2026-06-15 session)

### (1) Chat-inline build 斷線/凍屏 — **修了 (prod, 已驗)**
根因(spc-cpk 事件):chat 內跑 build 每 LLM round ~50s 不發 event → SSE 靜默
→ 撞 nginx `proxy_read_timeout 120s` → `Broken pipe`(Java log)→ 後端瞎建、
前端永遠凍在最後畫面。修法:`/chat`+`/build` 串流包 `_with_keepalive`,閒置每
10s 發**真 `ping` event**(不是 SSE comment — Java Spring codec 會吞 comment)。
驗:重跑 spc-cpk `Broken pipe=0`,4m36s 跑完。commit `62e3790`。

### (2) 協作式 Brief「build 前一律對齊」— **flag ON (prod, 已驗)**
把「要不要對齊」從 haiku 判斷改成 graph 確定性 gate:chat **一律**在 build 前出
一張 brief 卡,每個待決點 = 選項 + **「其它」自由描述**(Claude-cowork 風),
**全部選完自動開始建**(無手動「開始建」鈕)。
- flag `ENABLE_INTERACTIVE_BRIEF`(prod **ON**,2026-06-15)。
- backend:`intent_completeness` 一律出 brief(prompt 加 `is_pipeline_request`
  讓 knowledge-Q 仍 bypass);`dimensional_clarifier` 加 `OTHER_VALUE` free-text
  + 無歧義退化成 `__confirm__` 單一「開始」decision;`augment_goal` 支援自由
  文字;`tool_execute` 併 `client_context.intent_resolutions`(free-text 有空白
  不能走 prefix)。
- frontend:`DesignIntentCard` 加「其它」輸入 + auto-submit + data-testid;
  `AIAgentPanel`/`ChatPanel` 傳 `interactive_brief` + `intent_resolutions`。
- **無窮迴圈 bug + 修正(`37acfec`)**:brief 卡每次送 `[intent_confirmed:<id> dim=val]`
  (帶選擇),但 `intent_completeness` bypass regex 是 `[\w-]+\]`(要求 id 後立刻接
  `]`),選擇前的**空格**讓它不 match → 不 bypass → 每輪重發 brief → 無窮問。
  修:regex 改 `[^\]]*\]`。**教訓**:先前「3x 綠」只驗「build POST 有送」沒驗
  「送出後不再跳第二張 brief」,所以漏掉迴圈。
- 驗(修正後,正確驗法):backend unit;Playwright `brief_flow.spec.ts` 加
  **loop guard**(resolve 後等 90s 斷言**沒有新 brief 卡**)+ 同步 submitted 標記,
  **連 3 次全綠(A/B/C)**;backend 5 個 resume 全 bypass、零 re-emit。
  `tooling/gui_smoke.sh --suite brief`。
- commits `82b179f`→`f9e5933`。flag prod **ON**。
- **下一步**:option (a) plan-structured brief(agent 寫 step plan + 每步 LLM 生問題,
  已批准 spec)—— 待做。

---

## 0a. Knowledge 分層 + RAG (V58/V59, 2026-06-14 session) — **prod ON**

起點：研究 spc-ooc 為何 38 步。根因不是缺知識 —— id 36「全廠聚合 →
list_objects + foreach」早就寫好，但它是 **block-choice 知識卻只在 goal_plan
（block-agnostic，壓平它）被讀，phase_loop（真正選 block 的層）一條都沒注入**。
知識送錯樓層。

### 做了什麼

| Phase | 內容 | commit |
|---|---|---|
| V58 P1 | `agent_knowledge` 加 `applies_to`('plan'/'execute'/'both') + `always_on`；26 條重分類（4 core / 11 execute-relevant，過去 0 條到得了 execute） | `a47a192` |
| V58 P3 | layer-filtered retrieval：Java `searchByEmbedding(:layer)` + `highPriority(layer,alwaysOnly)`；sidecar `build_knowledge_hint` 加 layer/always_only/include_always_on/rag_limit | `a47a192` |
| V58 P2 | phase_loop 在 pick sub-phase 注入 execute-layer RAG（依 phase goal，top-3，不灌 always-on dump） | `a47a192`,`17b4126` |
| V58 P4 | `tools/knowledge_recall/measure.py` recall harness（gate：execute ON / layered OFF） | `a47a192` |
| V59 | id 36/37 改 **raw fan-out 優先**（list_objects+foreach get_process_info），移除 Pattern B（get_process_summary）。user 決策：不依賴預聚合 summary MCP | `21749d6` |

### 結果（spc-ooc，execute_knowledge:on）
- **p1：19 → 4/4/4**（確定性，3/3）。知識直接指 Route A，不再撞 process_history 死路。
- 走 raw `get_process_info` fan-out（user 要的可稽核路徑），無 get_process_summary。
- **SLASH-17 全套 17/17 finished+ok，無 regression**；spc-xbar-r-pair 還升級到專用 `block_xbar_r`。總 wall −28%。

### Flag 狀態（prod EC2 .env）
- `ENABLE_EXECUTE_KNOWLEDGE=1` **已開**（spc-ooc p1 19→4 + SLASH-17 17/17 驗證後）。
- `ENABLE_LAYERED_PLAN_KNOWLEDGE` **維持 OFF** —— recall harness 顯示 id 36 在
  plan 層 RAG miss，always-on dump 留著當安全網。要開先把 plan recall 做起來。

### 殘留 follow-up
- `get_process_summary` 的 `by_tool` 有 description↔runtime 欄位不一致（doc 說
  `ooc_count`，runtime 給 `count`）。現已非熱路徑（知識不再導向它），但要嘛修
  simulator 補欄位、要嘛改 description 講實話。MCP 仍 active。

---

## 0. SLASH-17 全綠 milestone (2026-06-13 session) — **17/17 OK**

一個個跑 SLASH-17，失敗就深挖根因 → 模擬確認 → 修 → 驗。最終 17/17 finished+ok
（effort=medium，per-call 慢但會完成；user 接受 users 願意等）。

### 這趟的修正（都已 deploy 到 EC2）

| 修正 | commit | 解了哪些 case |
|---|---|---|
| Phase-loop refine bundle: `next_memo` + `strict_phase_verify` + `construct_param_doc` (3 flags) | `231fe56` | spc-cpk 的 false-success 偵測 |
| **next-memo TypeError fix** — `next` arg 被傳進 BuilderToolset.add_node → 每個帶 next 的 mutation crash → flail / abort-orphan。dispatch 前剝掉 next。 | `8e50a15` | **spc-cpk / spc-multi-step / patrol-status**（3 個 abort-orphan/flail 一次解） |
| `LLM_REASONING_EFFORT` env-control（測 low = wash，退回 medium） | `a6a4630`,`765286d` | 速度槓桿（結論：effort 不是乾淨的贏） |
| **V57 knowledge** — 多 entity 比較 = 1 source + filter('in')，不要每台一個 fetch+union | `ae8b25c` | **spc-multi-tool**（枚舉 fan-out → orphan） |
| **inspect-formatter + cap** — `inspect_node_output` 結果只顯示 cols[:8]+省略 sample → 藏住 is_ooc → re-inspect 迴圈燒 round。改顯示全欄位+sample；`MAX_REACT_ROUNDS` 16→32；修 chart/alarm=12 stale bug。 | `8d167cc` | **ooc-pareto**（handover → finished pareto） |

### 關鍵教訓
- **concrete-column plan 不可行**（實測）：planner 在抓資料前 plan，欄位只能猜，而 ontology 欄位名（eventTime/toolID/name）跟常識（timestamp/equipment_id/chart_name）不一樣 → verifier 拿 plan 欄位去檢查會誤殺對的 build。現有「plan 只寫 intent、不列欄位」是對的設計。
- **per-call latency（~15-22s）是核心約束** → 被 round budget 綁死。能做的：(a) 別讓快撞牆時被砍頭（cap↑），(b) 別浪費 round（inspect 去重 / 截斷修正）。

### 殘留的小語意 nit（非失敗，待追）
- spc-trend / spc-multi-tool：chart 沒只濾到指定範圍（前者沒只 xbar，後者沒縮到指定 5 台）。
- spc-xbar-r-pair：用 line_chart+facet 代替專用 block_xbar_r（少嚴格 WECO R1-R8）。
- 這些是「種類對、做法合理、語意不 100% 精準」，strict_phase_verify 只擋種類擋不到。

---

## A. Builder Accuracy & UX — SLASH-13 thread (2026-06-12~13)

起點：SLASH-13 (`apc-recipe-compare`, tpl =「EQP-01 過去 14 天每個 recipe 的 APC
etch_time_offset 分佈 box plot 對比」) 一直 false-success — build 報成功但
box_plot 用 `x='step'` 而非 by recipe。根因鏈一路挖到最源頭：agent 在 p1 把
`object_name` 設成 `APC` → source 端只回 APC 維度、RECIPE 被丟掉 → 下游永遠拿不到
recipe 分組維度。實打 EQP-01 真實資料證實：`object_name` 留空時單一 event 同時含
`APC.parameters.etch_time_offset` 與 `RECIPE.objectID`，資料+blocks 完全支援，只是
agent 填錯一個選填參數。

### Done + deployed（main，已上 EC2）

| # | 項目 | commit | 驗證 |
|---|---|---|---|
| C2 | `ENABLE_STRICT_PHASE_OUTPUT`：finalize 偵測「plan 要 presentation kind 但 pipeline 無對應 terminal block」→ `failed_missing_output`（不再 silent finished）。builder_verify.py exit code 反映真實成敗。 | `702ec84` | unit tests + 真 catalog e2e |
| Fix 1 | process_history block doc：`object_name` 改成「強烈建議留空」+ 點名跨維度需求務必留空；修掉誤導的 perf tip（原本鼓勵指定）。 | `0d93e78` | 3x e2e |
| Fix 2 | 30-col picker cap：`_preview_output` 加 `all_columns`（解耦欄位名單 vs sample data，sample 維持 30 寬不爆 agent token）；`useUpstreamColumns` 讀 `all_columns`；SchemaForm column picker `<select>` → 可搜尋 `input+datalist` combobox。 | `8f057c7` | tsc + 後端實測 250 欄 |

**SLASH-13 結果：修好了，3/3 真正正確** —— 三次都 `object_name` 留空 + box_plot
x 軸綁到 recipe 維度（修正前：object_name=APC + x=step）。

### Pending follow-ups（小）

- [ ] **FU1 — DB block doc 同步**：Fix 1 只改了 `seed.py`（builder/agent 的來源）。
  `pb_blocks` DB + 前端 BlockDocsDrawer 看到的 process_history doc 仍是舊的。
  三邊一致性需手動 `psql` 更新 DB description（Flyway prod 停用，見
  `feedback_flyway_disabled_in_prod`）。
- [ ] **FU2 — Fix 2 瀏覽器 smoke**：datalist 搜尋 picker 已過 tsc + 後端實測，
  但還沒在真實瀏覽器點過手感（搜尋下拉、custom 值、清空）。

---

## B. Proposed — spec 待定/待開做

- [x] **Fix 5 — block_select 引導式 fields 編輯器**（觸發：user「誰會填這個」）
  - **Phase 1 DONE**（`2c60bfb`）：`FieldsEditor.tsx` repeating rows
    `[path picker][as][刪除]` + 「+ 新增」；path 用 datalist 上游頂層欄位 + 自由打字
    巢狀路徑。SchemaForm 用**形狀偵測**（array of object-with-`path`）觸發 —
    因 frontend param_schema 來自 pb_blocks DB（非 seed.py），shape 偵測不需動 DB。
    DB 已驗證 shape 會觸發。**待真實瀏覽器點過**（FU2-style）。
  - [ ] **Phase 2（待做）**：路徑 picker 從上游 **sample 自動展開巢狀路徑**
    (`APC.parameters.etch_time_offset`、`RECIPE.objectID` ...)；順帶用同一套修
    block_filter 的 nested column picker（現在只列得出頂層 `APC`/`RECIPE`）。

- [x] **ENABLE_CONSTRUCT_PARAM_DOC — construct 階段注入「正在填的 block 參數文件」**
  — **DONE**（`231fe56`，phase-loop bundle 三 flag 之一）。construct/tune 分支注入
  pending node 的 block param doc（含 process_history object_name 留空指引）。

- [ ] **Chart-axis-vs-intent 語意 verifier**
  - C2 只擋「缺交付物」，擋不住「chart 畫了但 x 軸/分組選錯」(x='step' 那類)。
  - 設計：chart phase 多一個 deterministic 檢查 —— plan 說 by recipe，但 chart 的
    x/group 參數沒對到 recipe 維度 → reject 逼重填，而非放 ADVANCED。
  - 屬「事實比對」非 case rule（同 C2 性質，寫在 graph node）。

---

## C. Backlog

### Memory v2 Spec — semantic-driven memory management

**Status**: 想法成型，spec 待寫
**Trigger**: 2026-05-21 session — 體認到 prompt 跟 agent flow 的可調空間已耗盡（CLAUDE.md §0「禁止 case-specific prompt rule」+ feedback_flow_in_graph_not_prompt），剩下唯一高槓桿就是 memory 系統升級。
**Why now**: EQP-08 case 顯示 agent 選錯 chart type（bar 而非 line/xbar 畫 SPC value vs limits），原因是缺一條 chart-selection knowledge；廣義來說 builder 蓋 N 次 SPC pipeline 後選 chart 的能力跟第一次完全一樣，因為 builder 端只讀不寫 memory。

#### 現況盤點

| Memory 表 | 內容 | 誰讀 | 誰寫 |
|---|---|---|---|
| `agent_knowledge` | 手寫 first-principle（SPC/APC/FDC level、視覺化必須含 chart block） | chat + builder plan_node（priority=high always-on + RAG cosine） | 只能人工 seed（V32/V36/V44 Flyway migrations） |
| `agent_experience_memories` | LLM 自動抽出 (intent → action) pair + confidence/use/success/fail counters | chat `load_context`（RAG by query） | chat `memory_lifecycle_node` 每次成功對話後自動寫 |
| `agent_memories` | legacy keyword-based | chat fallback | 廢棄 |

**Gap**：builder 側完全沒有「自動寫」的路徑 — `plan_node` 只讀 `agent_knowledge`，build success 後不抽 lesson 寫回。

#### 4 個必須先答的設計問題

1. **抽取觸發點**：(a) build success / judge accept 後 / (b) user 在 trace UI 主動標好壞 / (c) Skill 綁定 N 次無 error 後升級 confidence / (d) 三者組合分 tier？
2. **語意 unit schema**：raw plan JSON 會 over-fit instruction wording；free text 會跟 prompt 一樣失控。傾向結構化 triple `(intent_signature, block_chain_pattern, why)`，e.g. `(intent="SPC value vs limits trend", pattern="long_form → line_chart{y=[value,ucl,lcl]}", why="value 跟 limits 同單位連續量")`。schema 設計就是整個系統天花板。
3. **Retrieval 適用判斷**：純 cosine 太脆（中/英/同義詞 miss）；建議 hybrid: cosine 第一關 → metadata gate（intent_type, data_subject, output_kind）第二關。需要先有 intent classifier 把 instruction 拆 facet。
4. **Conflict / staleness**：Memory A 說「用 line_chart」、Memory B 說「用 xbar_r」誰贏？block schema 改了 → 舊 memory stale 怎麼自動偵測？chat 側已有 confidence_score + use_count + fail_count，builder 要不要照搬？

#### Next step

寫單頁 Spec（30-60 分鐘），對 4 個問題各給明確答案 + schema 草案 + 「EQP-08 走過去會怎樣」worked example。Spec 確定後再分 phase 實作。

**Do NOT**: 一邊寫 V45 chart-selection knowledge 一邊做 builder reflection node — 那會做出「能跑但語意還是平的」memory。Spec 先。

---

## 參考 — EC2 deploy state (2026-06-14)

- HEAD: `21749d6`
- perf flags ON：`prompt_cache` `atomic_add_connect` `auto_verifier`
  `no_duplicate_node` `rich_canvas_snapshot` `plan_knowledge` `strict_phase_output`
  `construct_param_doc` `strict_phase_verify` `next_memo`
  **`execute_knowledge`（V58，2026-06-14 開）**
  （`strict_tool_id` + `auto_signal` + `layered_plan_knowledge` 仍 OFF）
- 服務：aiops-app:8000 / aiops-java-api:8002 / python-sidecar:8050 / ontology-sim:8012（全 HEALTHY）
