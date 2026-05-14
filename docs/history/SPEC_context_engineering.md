# SPEC — Agent Context Engineering

**Date:** 2026-04-27
**Status:** Draft — pending approval
**Author:** Gill (Tech Lead) + Claude

---

## 0. Motivation

2026-04-27 測試：使用者打「STEP_001 最近怎樣？」，agent 直接跳 Glass Box Pipeline Builder 建出 7-node pipeline、燒 90k input tokens、撞 `MAX_ITERATIONS=10`。問題不在 LLM、不在 Pipeline Builder — 在於 agent 拿到 *vague* query + 沒有 *current state* prior，只能反射性地包山包海。

兩個獨立但互補的 gap：

1. **Intent disambiguation** — vague query 應該先確認，而不是立刻 build pipeline
2. **Dynamic context injection** — agent 應該知道「現在有 3 個 alarm + EQP-03 OOC + user 剛在看 STEP_001」，而不是每次從零猜

兩個都做完，這類 query 的 token 用量 / latency 至少砍半，回答更精準。

---

## Part A — Intent Disambiguation

### A.1 設計

新增 `intent_classifier_node`，位置在 [load_context_node](python_ai_sidecar/agent_orchestrator_v2/nodes/load_context.py) 之後、[llm_call_node](python_ai_sidecar/agent_orchestrator_v2/nodes/llm_call.py) 之前。一次輕量 LLM call（Haiku 4.5 或 Sonnet 4.5 + `max_tokens=200`），輸出 enum：

| Intent | 範例 query | 後續行為 |
|---|---|---|
| `clear_chart` | 「給我 EQP-03 的 xbar 控制圖」 | 直跳 Pipeline Builder（現況路徑） |
| `clear_rca` | 「STEP_059 為什麼一直 OOC」 | 走 RCA flow（v1 chat orchestrator） |
| `clear_status` | 「現在有幾個 alarm」 | 直接從 dynamic context 答（Part B） |
| `vague` | 「STEP_001 最近怎樣」 | 觸發 clarify SSE event |

### A.2 Clarify SSE event

新 event type：

```
event: clarify
data: {
  "question": "你想看哪一面？",
  "options": [
    {"id": "spc",    "label": "SPC 趨勢圖",   "preview": "Xbar/R/S/PC 4 張圖"},
    {"id": "alarms", "label": "最近 alarms",  "preview": "24h 內 3 個 OOC"},
    {"id": "rca",    "label": "RCA 分析",     "preview": "找出最近 OOC 根因"}
  ],
  "fallback_label": "全部都要（建完整 pipeline）"
}
```

Frontend 新增 `<ClarifyCard>` component（風格跟現有 PlanRenderer / suggestion_card 一致）。User 點選 → 訊息 re-submit，前綴 `[intent=spc]` / `[intent=alarms]` / `[intent=rca]`。fallback 路徑把 message 原樣送回，這次 classifier 會被略過。

### A.3 邊界情境

- Classifier 自身有 cost ≈ +200 tokens / +500ms。**只在 `vague` 觸發 full Pipeline Builder 之前才划算**，否則 net loss。
- Confidence threshold 要調 — 太敏感（每句都 clarify）很煩；太鬆（什麼都當 clear）等於沒做。建議 threshold 0.7，初期偏保守。
- 「全部都要」逃生口必須有 — power user 不想被打斷時要能直接打過去。
- Classifier prompt 要包**短的 keyword pattern + 範例**，不要 LLM 自由心證。例如 `「給我」+「圖」=clear_chart`、`「為什麼」+「OOC/異常」=clear_rca`。
- 多語言：中英混打都要過。

---

## Part B — Dynamic Context Injection

### B.1 設計

擴充 [load_context_node](python_ai_sidecar/agent_orchestrator_v2/nodes/load_context.py)：除了現有的 MCP / Skill / Role catalog，再叫一個新 aggregator endpoint 拉**當下狀態**。

| 來源 | 內容 | 範例 |
|---|---|---|
| Java `/internal/alarms?status=active&limit=10` | active alarms | `["EQP-03 STEP_001 OOC since 2h", ...]` |
| Java `/internal/process/ooc-summary` | OOC tools snapshot | `{"oocs": ["EQP-03", "EQP-07"], "as_of": "..."}` |
| Java `/internal/triggers/recent?limit=5` | 最近自動觸發 | `[{name: "STEP_059 patrol", fired_at: "..."}]` |
| Frontend `client_context` (新增 ChatRequest field) | user 視角 | `{selected_equipment: "EQP-03", current_page: "topology"}` |

聚合在 Java 一個新 endpoint：`GET /internal/agent-context-snapshot`（呼叫 Java 比 sidecar 各自打 4 個 endpoint 省 round-trip + 有 caller_roles middleware）。

### B.2 注入位置

不放 system prompt（會破 Anthropic prompt cache — 每次 dynamic block 不同），改成**第一個 user message 前面的 `<current_state>` block**：

```xml
<current_state ts="2026-04-27T06:18">
  active_alarms: 2 (EQP-03 STEP_001 OOC@2h, EQP-07 STEP_002 OOC@30m)
  ooc_tools: [EQP-03, EQP-07]
  recent_triggers: [STEP_059_patrol@10:15, STEP_001_check@09:50]
  user_focus: EQP-03 (topology page)
</current_state>

User: STEP_001 最近怎樣？
```

LLM 看到這個 block 就有充分 prior：EQP-03 已 OOC + user 在看 EQP-03 → 應該聚焦在「EQP-03 STEP_001 OOC 的具體狀況」而不是包山包海建 7 個 chart。

### B.3 邊界情境

- **Cache impact** — 每次 dynamic block 都不一樣 → user message 部分不能 cache。但 system prompt（catalog + role）仍然 cache 命中，整體 cost 影響可控（system 部分通常占 60-80% input tokens）
- **Bloat** — 設 **1KB hard cap**。alarms list 取最近 10 個、每個只放 `equipment_id / step_id / age / status`，不放 detail
- **Stale** — snapshot 在 request 進入時取一次，正常處理時間 1-2 分鐘內 user 不會察覺；snapshot 太舊（>5min）就重抓
- **Cross-tenant / 角色** — aggregator endpoint 用 caller_roles 過濾：ON_DUTY 看自己機台、PE 看全廠、IT_ADMIN 看全部
- **Frontend `client_context` schema** — 漸進式加，先 `selected_equipment_id` 一個欄位，之後再加 `last_viewed_alarm_id`、`current_page`、`recent_chart_ids`
- **空 state** — alarms / OOC / triggers 都空時，block 本身仍然要送（避免 LLM 以為 context loader 失敗 / 漏資料）

### B.4 Java aggregator endpoint contract

```http
GET /internal/agent-context-snapshot
Authorization: Bearer <internal-token>
Headers:
  X-Caller-Roles: IT_ADMIN,PE
  X-Caller-User-Id: 123

Response (200):
{
  "as_of": "2026-04-27T06:18:33Z",
  "active_alarms": [
    {"equipment_id": "EQP-03", "step": "STEP_001", "status": "OOC",
     "age_seconds": 7200, "alarm_id": "alm_abc"}
  ],
  "ooc_tools": ["EQP-03", "EQP-07"],
  "recent_triggers": [
    {"name": "STEP_059_patrol", "fired_at": "2026-04-27T05:50:00Z"}
  ]
}
```

caller 把 frontend `client_context` 也帶進這個 request body，server 直接打包好 final block 回給 sidecar，避免 sidecar 還要再組字串。

---

## 1. 為何 Part B 應該先做

| | Effort | Impact | UX 動 | LLM cost |
|---|---|---|---|---|
| **Part A** | 2-3 day（新 node + clarify UX + classifier prompt 調 + 測試）| 高（vague query 不爆 token）| 是 | +classifier call |
| **Part B** | **1 day**（純後端：aggregator + load_context 加 1 step + system prompt template 加 block）| 高（連 clear query 也受益）| 否 | -prompt 內容更精準，主 LLM call 收斂快 |

Part B 不動 UX，純後端。Part A 要動 chat UX + 寫 classifier。**先做 B 風險低、回收快**；做完 B 觀察一週「最近怎樣」這類 query 是否已能答得不錯，再決定 A 還要不要做（或者 A 縮小範圍只 cover B 沒涵蓋的剩餘 vague query）。

---

## 2. Step-by-Step Execution Plan

### Phase 1 — Part B（1 day）

1. Java：新 endpoint `GET /internal/agent-context-snapshot`，聚合 alarms / ooc / triggers，套 caller_roles 過濾
2. Frontend：`ChatRequest` 加 `client_context: { selected_equipment_id?: string, current_page?: string }`，AppContext 已有 `selectedEquipment` 直接接
3. Sidecar：`load_context_node` 多一步 — 打 `/internal/agent-context-snapshot`（接受 client_context as body），把 response 組成 `<current_state>` block 注入到 user message 前
4. Tests：3 個 sample query（`STEP_001 最近怎樣` / `EQP-03 為什麼 OOC` / `現在有幾個 alarm`）+ inspect prompt + count tokens

### Phase 2 — 觀察期（1 週）

跑日常使用，看：
- token 用量是否下降
- 平均 iteration 數是否下降（10 是否還會撞）
- vague query 是否答得更聚焦

### Phase 3 — Part A（2-3 day，視 Phase 2 結果決定要不要做）

1. Sidecar：新 node `intent_classifier_node`，加在 `load_context` 之後 / `llm_call` 之前
2. Sidecar：新 SSE event type `clarify`
3. Frontend：新 `<ClarifyCard>` component + dispatch 處理
4. Frontend：clarify 點選後 message re-submit with `[intent=...]` 前綴
5. Tests：8 個 sample query（4 clear + 4 vague）+ classifier 路由正確 + 「全部都要」逃生口

---

## 3. Edge Cases & Risks

- **Classifier 自己變 bottleneck** — 萬一 Haiku 也要 1 秒，user 會覺得「打字後等好久才有 clarify」。先用 Sonnet 4.5（小 prompt + max_tokens=200），實測 latency
- **Dynamic context 拖慢 first-byte** — aggregator endpoint 必須 <300ms，超過就 timeout fallback（送沒有 context 的舊 prompt）
- **Memory 系統重複** — 已有 vector memory 拉 past sessions。動態 context 是「現在狀態」、memory 是「過去經驗」，互補不衝突，但 prompt 太長要注意
- **離線測試難** — dynamic context 取決於 simulator 當下狀態，CI 跑 e2e 要有固定 fixtures

---

## 4. Open Questions

1. Aggregator endpoint 放 Java 還是 sidecar？（推薦 **Java** — 已接 DB + caller_roles middleware）
2. ClarifyCard UX 是 inline chat 卡片還是 modal？（推薦 **inline**，跟 Plan card / suggestion_card 一致）
3. Intent classifier 用什麼 model？（推薦 **Sonnet 4.5 + max_tokens=200**，比 Sonnet 4 快、比 Haiku 4.5 準）
4. `client_context` 從哪些頁面收集？目前 AppContext 有 `selectedEquipment` / `triggerMessage` / `contract` / `investigateMode` / `dataExplorer`。最有用的應該是前兩個 + page route
5. dynamic context 要不要也餵給 Glass Box Pipeline Builder agent？（建議 **要** — Pipeline Builder 也會因「user 在看 EQP-03」而選對 source params）
