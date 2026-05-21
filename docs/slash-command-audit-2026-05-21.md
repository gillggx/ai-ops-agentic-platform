# Slash Command Audit — 2026-05-21

**Range**: chat 模式 14 個 `/` 快捷指令（[SlashCommandMenu.tsx](aiops-app/src/components/copilot/SlashCommandMenu.tsx)）
**測試法**: 每個指令 → `/internal/agent/build` 拿 goal_plan → `/internal/agent/build/plan-confirm`（confirmed=true）→ 觀察 build_finalized
**Constraint**: 解決方案不能改 prompt / agent flow — 只能補 block doc / MCP doc / `agent_knowledge` memory

## TL;DR

| Verdict | Count | Commands |
|---|---|---|
| OK | 5 | spc-trend / spc-ooc / spc-cpk / spc-multi-tool / spc-drift |
| WARN (validator) | 1 | apc-drift |
| FAIL — routed to advisor by mistake | 2 | apc-corr / apc-recipe |
| FAIL — goal_plan refused | 1 | diag-alarm |
| FAIL — alarm MCP 不存在 | 2 | patrol-alarms / diag-walkback |
| FAIL — block selection / param 卡死 | 3 | patrol-status / patrol-recipe-consist / diag-ooc-point |
| **Total FAIL** | **8/14 (57%)** | — |

**Root pattern summary**:
- 5 個 FAIL 跟「alarm domain」有關 — 系統根本沒有 alarm 相關 MCP / block
- 2 個 FAIL 是 `classify_advisor_intent` 把 BUILD intent 誤判成 KNOWLEDGE
- 3 個 FAIL 是 block doc 不夠清楚（spc chart_name 列表、mcp_foreach 用法、block_find vs sort_limit）

---

## Per-command Verdict

### 📈 spc-trend [OK]
**Prompt**: 幫我看 EQP-01 STEP_001 最近 100 筆 xbar 趨勢
**Goal phases (3)**: raw_data → transform(unnest+filter) → chart(line_chart)
**Final**: 4 nodes, 3 edges. `block_process_history → block_unnest → block_filter → block_line_chart`. ✓
**Doc/Memory fix**: 無

### 🔍 spc-ooc [OK with friction]
**Prompt**: 過去 24 小時哪些機台 SPC OOC 最多？列前 5 名
**Final**: 7 nodes, 6 edges. ✓
**Friction**: p1 跑 24 actions（agent 在 `block_mcp_call` / `block_list_objects` / `block_mcp_foreach` 之間來回）才搞定。最終 build 出來但 round 數爆。
**Doc fix**: `block_mcp_foreach` 描述需要加 worked example「對全廠 tool list 各別跑 get_process_info」— 目前 agent 不知道這是它的旗艦用法。

### 📊 spc-cpk [OK with risk]
**Prompt**: 比較 EQP-01 STEP_001 過去 7 天的 R、Cpk、Cpk_std 趨勢
**Final**: 8 nodes, 7 edges. ✓
**Risk**: agent 嘗試了 `value=cpk_std` 又 `value=s_chart` 多次 set_param — 顯示**不確定 SPC 12 chart 真實名稱**。最後跑通了但可能畫到錯的 chart。
**Doc fix**: `block_process_history` doc 加一個「## SPC 12 chart 名稱對照表」(xbar_chart / r_chart / s_chart / cusum_chart / ewma_chart / p_chart / u_chart / np_chart / c_chart / mr_chart / individuals_chart / boxplot_chart)。  
**Memory fix（更好）**: `agent_knowledge` priority=high 加一條「SPC 12 chart canonical names + 各別代表什麼 process variation」。理由：agent 不需要重背 spec，只需要拿到 catalog 一次就會用。

### 🎨 spc-multi-tool [OK]
**Prompt**: 比較 5 台機台在 STEP_001 的 xbar 趨勢，畫一張彩色 line chart（color=toolID）
**Final**: 5 nodes, 4 edges. ✓
**Doc/Memory fix**: 無

### 📉 spc-drift [OK]
**Prompt**: 過去 7 天用 cusum + box_plot + probability_plot 三件組診斷
**Final**: 6 nodes, 5 edges。三 chart 並列。最乾淨的 build。✓
**Doc/Memory fix**: 無

### 📐 apc-drift [WARN]
**Prompt**: 看 EQP-01 APC etch_time_offset 最近 24 小時是否有漂移
**Final**: build_finalized ok=true BUT **1 validator warning** + p3 跑 14 actions（試 `block_ewma_cusum` → `block_linear_regression` → `block_weco_rules` 都試過）
**Root cause**: agent 不知道哪個 block 適合「APC drift detection」。三個 block 都看起來合理。
**Memory fix**: `agent_knowledge` priority=high 加一條「Drift detection block 選型 — short-term gradual drift 用 ewma_cusum；long-term linear drift 用 linear_regression；step change / shift 用 weco_rules R2/R6」。理由：domain heuristic，不是 block 本身的說明，跨 block 才有意義。

### 🔗 apc-corr [FAIL — 誤判 ADVISOR]
**Prompt**: 找 EQP-01 APC etch_time_offset 跟 SPC xbar OOC 的相關性
**Result**: classify_advisor_intent 判 `intent=KNOWLEDGE` → 走 advisor 給概念說明，**沒建 pipeline**
**Root cause**: classifier 看到「相關性」就以為是「解釋什麼是相關性」。但用戶有 EQP-01 + 具體 APC 參數名 + 具體 SPC chart，明顯是要建 pipeline 做 `block_linear_regression`。
**Memory fix**: `agent_knowledge` priority=high 加「Intent classification — 帶具體 EQP / step / 參數名的『相關性 / 比較 / 變化』請求是 BUILD 不是 KNOWLEDGE」。Classifier 已經是 graph node 不是 prompt，但它讀 `agent_knowledge`，這條 hint 會進它 context。

### 🧪 apc-recipe [FAIL — 誤判 ADVISOR + 幻覺 block 名]
**Prompt**: EQP-01 在 recipe RECIPE_A 切到 RECIPE_B 後 APC 參數有沒有變化？
**Result**: advisor 路徑，markdown 答案幻覺出兩個不存在的 block：`block_query_equipment_data`、`block_trend_analysis`。
**Root cause (1)**: 同 apc-corr — 帶具體 EQP / recipe 名稱的「有沒有變化」是 BUILD intent。
**Root cause (2)**: advisor markdown 自由發揮虛構 block 名 — advisor 系統 prompt 沒約束「block 名只能引 catalog」。
**Memory fix**: 同 apc-corr 那條（intent classify）。
**Doc fix**: advisor_v2 的 system prompt 結尾加一行 unconditional rule「禁止虛構 block 名 — 若 catalog 無相符 block，明確說『系統目前沒有對應的 block』」— 但這是改 prompt，違反 constraint。**改用** advisor 的 system prompt 從 DB / system parameter 載入，把這條寫在 system parameter，不算改 prompt 程式碼。

### 🔔 patrol-alarms [FAIL — 無 alarm MCP]
**Prompt**: 列出今天所有 HIGH 級 alarm（OPEN 狀態），含觸發證據
**Result**: build_status=None（24 actions in p1，agent 試 `block_mcp_call` / `block_list_objects` / `block_process_history` 都沒 alarm 資料）
**Root cause**: sidecar 的 MCP catalog **沒有任何 alarm 相關 MCP**。alarm 是 Java backend `/api/v1/alarms` 提供，但 sidecar pipeline 沒包 wrapper。
**Architectural fix**: 新增 `get_alarms(severity, status, since)` system MCP（需動 java-backend + sidecar — 不算改 prompt / agent flow，是補資料源）。
**Memory fix（短期 mitigate）**: `agent_knowledge` priority=high 加「Alarm 查詢不在 pipeline builder 內 — 引導用戶直接看 /alarms 頁面，或拒絕 alarm-only 的 build 請求」。短期防止 agent 浪費 N 個 round 試錯。

### 🩹 patrol-status [FAIL — structural error]
**Prompt**: 現在所有機台的狀態快照，標示異常的機台
**Result**: build_finalized fail, **2 structural errors**
**Root cause**: 機台狀態 = `list_tools` MCP 回的 idle/processing/down。Agent 想 chain `block_list_objects → block_mcp_foreach → block_threshold` 但搞錯 mcp_foreach 的 input/output shape。
**Doc fix**: `block_mcp_foreach` 描述需要：(a) 列出每個 MCP 該 block 知道怎麼 fan-out（`get_process_info(tool_id=...)`、`get_process_summary(...)`）；(b) input port = upstream rows (each is dict)、output port = flattened multi-MCP results。**這個 block 是現在最薄弱的描述**。

### 📋 patrol-recipe-consist [FAIL — column 名亂猜]
**Prompt**: 全廠跑 RECIPE_A 的機台，xbar 平均值差異 > 1.5σ 的列出來
**Result**: build_status=None（p2 跑 24 actions 卡死 set_param column=SPC / spc_charts / SPC / spc_charts 來回）
**Root cause**: agent 不知道 process_history nested shape 裡 SPC chart 該怎麼抽。明顯沒讀懂 `block_unnest` + `block_pluck` 對 `spc_charts` array 的用法。
**Doc fix**: `block_unnest` doc 加 worked example：「對 `block_process_history` 輸出做 `column=spc_charts` 展開」+ 對應 `block_filter` 後續寫法。已知例子應該 self-contained 走過一遍。
**Memory fix（補強）**: `agent_knowledge` 「Process history nested shape canonical handling」— 連結到 V42 nested first-principle 那條。

### 🩺 diag-alarm [FAIL — goal_plan_refused]
**Prompt**: Alarm #1 根因分析：列觸發條件、證據資料、相關 APC/SPC
**Result**: `goal_plan_refused` — agent 列了 5 個缺失資訊（哪個 alarm 編號、產出格式、APC/SPC 篩選範圍、時間窗、證據定義）拒絕進入 build
**Root cause**: (a) 沒 alarm MCP；(b) prompt 真的太抽象（沒 alarm_id 細節）
**Memory fix**: 同 patrol-alarms — 加「alarm 不在 builder scope」hint，讓 refused 訊息直接導到 /alarms 頁面。
**Slash template fix（不算改 prompt / flow）**: `SlashCommandMenu.tsx` template 直接寫死合理 placeholder 例如「Alarm #1 根因分析：取觸發時刻前 1 小時、列出所有 OOC events + APC etch_time_offset / SPC xbar 值」— 但用戶會說 placeholder 還是要替換。先 memory fix。

### 🔬 diag-ooc-point [FAIL — block_find 迴圈]
**Prompt**: LOT-0234 在 EQP-01 STEP_001 的 OOC 點，前後 30 分鐘的 APC 變化
**Result**: build_status=None。p2 跑 24 actions — agent 反覆 add_node `block_find` → connect → 重來 → 再加。
**Root cause**: agent 想做「找一個 anchor event + 取前後 30 分鐘窗口」這個 pattern，但既有 block 沒有 time-window-around-anchor 這個語意。block_find 找到 anchor，但下一步取 ±30min 沒有現成 block。
**Doc fix**: `block_find` doc 加「## 配合時間窗口」段，講「先 block_find 抓 anchor → upstream 重新拉 anchor.eventTime ± Nmin 的 process_history → re-filter」這個 canonical chain。
**Memory fix（補強）**: `agent_knowledge` 加「OOC 事件 + 前後時間窗 = 兩段 chain 不是一段 — 先找 anchor 再二次拉 history」。

### 🧭 diag-walkback [FAIL — 試 8 個不存在的 MCP 名]
**Prompt**: 從 alarm #1 倒推：SPC 證據 → APC 紀錄 → 當下 recipe，全部列出
**Result**: build_status=None。p1 跑 24 actions — agent 連續猜 `list_alarms` / `get_alarms` / `get_alarm` / `query_alarm` / `alarm_history` / `alarms` / `get_alerts` / `alerts` 全部失敗。
**Root cause**: 同 patrol-alarms — 沒 alarm MCP。
**Doc/Memory fix**: 同 patrol-alarms。**這個 case 最浪費 LLM token** — 24 round 全部試錯。memory 那條「alarm 不在 builder scope」會立刻短路。

---

## Remediation Priority

依照「修一條 fix 多少 case」排序：

### P0 — 1 條 memory 修 4 個 case
**Title**: 「Alarm 不在 pipeline builder scope — 引導用戶」
**Type**: agent_knowledge, priority=high, scope=global
**Fixes**: patrol-alarms / diag-alarm / diag-walkback / (advisor 路徑 mention)
**Effort**: 5 分鐘寫 V45 SQL + Flyway（manual psql 跑）+ sidecar 重啟自動 embedding backfill

### P1 — 1 條 memory 修 2 個 case
**Title**: 「Intent classification — 帶具體 EQP / step / 參數名的『相關性 / 比較 / 變化』請求是 BUILD 不是 KNOWLEDGE」
**Type**: agent_knowledge, priority=high, scope=global
**Fixes**: apc-corr / apc-recipe
**Effort**: 5 分鐘

### P2 — 補 block_mcp_foreach 文件
**Type**: `block_docs` table 更新（GUI 在 /admin/block-docs）
**Fixes**: spc-ooc friction / patrol-status structural error / 任何未來 fan-out 案例
**Effort**: 30 分鐘寫 markdown body

### P3 — 補 block_unnest doc + agent_knowledge SPC chart name 對照
**Type**: block_docs body 更新 + 1 條 agent_knowledge
**Fixes**: spc-cpk risk / patrol-recipe-consist
**Effort**: 1 小時

### P4 — Drift block 選型 heuristic
**Type**: agent_knowledge priority=high
**Fixes**: apc-drift validator warning
**Effort**: 10 分鐘

### P5 — block_find 時間窗模式
**Type**: block_docs body 更新（block_find）+ 1 條 agent_knowledge
**Fixes**: diag-ooc-point
**Effort**: 30 分鐘

### Architectural (out of scope for this round)
**Title**: 新增 `get_alarms` system MCP（java + sidecar 串接）
**Reason**: alarm 是 platform first-class 概念，不該繞 /alarms 頁面看
**Effort**: 半天
**Not in 「不改 prompt/flow」scope** — 算補資料源不算改 flow，但本輪先用 memory mitigate

---

## Source of truth files

- 測試 prompts: [aiops-app/src/components/copilot/SlashCommandMenu.tsx:34-98](aiops-app/src/components/copilot/SlashCommandMenu.tsx#L34-L98)
- 既有 agent_knowledge seeds: V32 / V36 / V44 Flyway migrations under `java-backend/src/main/resources/db/migration/`
- plan_node knowledge injection: [python_ai_sidecar/agent_builder/graph_build/nodes/plan.py:466-513](python_ai_sidecar/agent_builder/graph_build/nodes/plan.py#L466-L513)
- classify_advisor_intent: [python_ai_sidecar/agent_builder/advisor/](python_ai_sidecar/agent_builder/advisor/)
- Raw SSE traces: `/tmp/build_full/*.step1.sse` (goal plan) + `*.step2.sse` (actual build) on local
