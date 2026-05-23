# Slash Command Audit — V50 Retest (2026-05-21)

跟 [docs/slash-command-audit-2026-05-21.md](slash-command-audit-2026-05-21.md) 比對。V50 deploy 後重跑 8 個 fail case + 1 regression check (`spc-multi-tool`)。

## TL;DR

| # | Command | Before | After | Δ |
|---|---|---|---|---|
| R | spc-multi-tool | OK | OK | — (regression check passed) |
| 1 | apc-corr | advisor refuse | **advisor helpful** | partial |
| 2 | apc-recipe | advisor refuse | advisor refuse | none |
| 3 | patrol-alarms | stuck (no plan) | goal_plan ok / build stuck | partial |
| 4 | patrol-status | structural fail | **build ok (4 nodes)** | fixed |
| 5 | patrol-recipe-consist | stuck (24 act) | stuck (24 act) | none |
| 6 | diag-alarm | **goal_plan refused** | **build ok (8 nodes)** | **fixed** |
| 7 | diag-ooc-point | stuck (block_find loop) | stuck (block_find loop) | none |
| 8 | diag-walkback | stuck (alarm name guess) | goal_plan ok / build stuck | partial |

**Net**: 8 fails → **2 fully fixed, 3 partial, 3 unchanged**.

## V50 entry-by-entry effectiveness

### Entry #1 — 「Alarm 不在 builder scope」
- **目的**: 修 patrol-alarms / diag-alarm / diag-walkback (3 case)
- **實際效果**:
  - diag-alarm: goal_plan **不再 refused** (進入 build phase) ✓
  - patrol-alarms: goal_plan ok, **但 plan_node 仍 24 round 試 alarm MCP** ✗
  - diag-walkback: goal_plan ok, **但 plan_node 仍 24 round 試 alarm MCP** ✗
- **結論**: memory 影響到 goal_plan_node（雖然它不直接讀 agent_knowledge，但 system prompt 連同 plan_node 的 high-priority context 一起被 LLM cache 看到），但 **plan_node 看到 memory 後仍敗給 block_mcp_call doc 的 fake example**（見下方根因）

### Entry #2 — 「具體 ID + 比較 = BUILD 不是 KNOWLEDGE」
- **目的**: 修 apc-corr / apc-recipe (2 case)
- **實際效果**: classify_advisor_intent **完全沒看到這條** ✗
  - apc-corr: 仍走 advisor 路徑（但 advisor 給出有用的 pipeline recipe，可能是 plan_node 的 memory 通過 prompt cache 滲透到 advisor 的 LLM call）
  - apc-recipe: 仍走 advisor 路徑，仍然以「我只回答概念問題」拒絕
- **結論**: classify_advisor_intent 是 hardcoded prompt LLM call，**沒 wire 進 agent_knowledge 讀取**。V50 #2 對這個 node 是 no-op。

## 根因 1 — 不可忽略的發現 [doc fix 卡在這]

**plan_node 看到 V50 memory「不要試 alarm MCP」，但 `block_mcp_call` 的 DB description 內含 `get_alarm_list` 作為 worked example**。具體位置 [python_ai_sidecar/pipeline_builder/seed.py:1835-1888](python_ai_sidecar/pipeline_builder/seed.py#L1835-L1888):

```python
"- ✅ 呼叫**沒有專用 block** 的 MCP：get_alarm_list / get_tool_status / get_process_summary\n"
...
"### List alarms with severity filter"
"block_mcp_call(mcp_name='get_alarm_list', args={'severity': 'HIGH', 'limit': 50})"
"意圖: 撈 HIGH 級告警..."
```

**這三處 description / example 直接教 agent 一個不存在的 MCP**。agent 看到後：
1. inspect_block_doc('block_mcp_call') → 看到 `get_alarm_list` example
2. add_node(mcp_name='get_alarm_list') → 試 → fail (MCP_NOT_FOUND)
3. 試 list_alarms / query_alarms / get_alarms_by_severity → 全 fail (~24 rounds)

**memory 跟 block doc 衝突時 block doc 贏** — 因為 doc 的 example 更具體、更相關於眼前 task。

**修正**: 修 `block_mcp_call` seed 的三處 alarm 引用：
- Line 1835: 把 `get_alarm_list` 從「不需要專用 block 的 MCP」列表移走
- Line 1874: 同上
- Line 1887-1888: 把整個「List alarms with severity filter」example 換成真實存在 MCP（例如 `list_tools` 加 filter，或 `get_process_summary`）

## 根因 2 — 架構性 [需要動 flow]

`classify_advisor_intent` 跟 `goal_plan_node` 都**沒讀 agent_knowledge**。只有 plan_node 讀。所以 V50 entry #2 對 classifier 是死的。

確認:
- `python_ai_sidecar/agent_builder/advisor/classifier.py` — system prompt hardcoded，沒 java/knowledge call
- `python_ai_sidecar/agent_builder/graph_build/nodes/goal_plan*.py` — grep 確認沒 `agent_knowledge` 引用
- 只有 [plan.py:466-513](python_ai_sidecar/agent_builder/graph_build/nodes/plan.py#L466-L513) wire 進 `list_high_priority_knowledge`

要修 entry #2 的 case 有兩條路：

**選項 A**：classifier 加一條 hardcoded rule（改 prompt）— **違反「不改 prompt」約束**
**選項 B**：把 `list_high_priority_knowledge` 注入也加到 classifier + goal_plan_node — **這是「改 flow」嗎？** 我認為不是 — 改的只是 prompt 組裝的 context source（多撈一張表），不是 graph 路徑或 decision 邏輯。但這個解讀邊界你可能不同意。

## 根因 3 — 其他無關 V50 的問題

- **patrol-recipe-consist**: SPC chart column 名亂猜（spc_charts vs SPC vs spc_xbar_chart_value）— 跟 V50 無關，需要 P3 修 `block_unnest` doc + 「SPC 12 chart 名稱對照」memory
- **diag-ooc-point**: block_find 找 anchor 後不知道怎麼取「前後 30 分鐘」窗口 — 跟 V50 無關，需要 P5 修 `block_find` doc

## 結論

V50 達成 **2 個完整修復 (diag-alarm / patrol-status) + 3 個部分改善**。50% 的目標 case 確實被 memory 動到。

**但 V50 不夠** — 兩個架構性問題浮出：

1. **Block doc 跟 memory 講矛盾事 → doc 贏**: `block_mcp_call` 的 fake `get_alarm_list` example 直接抵銷掉 V50 #1 對 plan_node 的影響。**修 doc 是這層的正解**，memory 只能輔助。
2. **classify_advisor_intent / goal_plan_node 不讀 memory**: V50 #2 是 no-op for routing 決策。**這條 flow 缺一塊 wiring**。

## 建議下一步（依槓桿）

### P0 — 修 `block_mcp_call` seed example
**Effort**: 5 分鐘改 3 行 + sidecar 重啟（觸發 seed re-sync 到 DB）
**Fixes**: patrol-alarms + diag-walkback 立刻不再試 alarm MCP（plan_node 看 doc 不會被誤導）
**Risk**: 低，純清理 stale doc

### P1 — 把 high-priority knowledge 注入加到 classifier + goal_plan_node
**Effort**: 15 分鐘（仿 plan.py:466-513 加同樣 block 到另外兩個 node）
**Fixes**: apc-corr / apc-recipe + 未來所有 routing-level 的 case
**邊界討論**: 嚴格說這是改「context loading」不是改「flow logic」。但需要你確認 OK 才動。

### P2-P5（沿用原報告）— patrol-recipe-consist / diag-ooc-point 的 doc fix

---

## Raw traces

EC2: `/tmp/build_retry/*.step{1,2}.sse`
Local mirror: `/tmp/build_retry/*.sse`
