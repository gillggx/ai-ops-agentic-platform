# SPEC — Auto-Patrol ↔ Pipeline Input Wiring + Event Registry

**Date:** 2026-04-28
**Status:** Draft — pending approval
**Author:** Gill (Tech Lead) + Claude
**Trigger:** 2026-04-28 砍掉所有舊 patrol/skill/pipeline 後，重建前先把 trigger → patrol → pipeline 的橋設計清楚。

---

## 0. Motivation

舊系統：patrol 用 `input_binding` JSON 字串自由表達，沒 type check、沒 UX 引導、schedule 觸發時 scope 沒地方填 → 新 wizard 點建立 HTTP 500，舊資料只能靠 SQL 改。

要做到「**事件觸發 / 排程觸發 / 指定時間**」三種 trigger 都能順 user 心意把 attribute 餵進 pipeline.inputs，需要三件事**一起做**：

1. **Event Registry 加 attribute schema**（每個 event_type 帶屬性定義）
2. **Patrol wizard 加 scope 選擇器**（schedule/once 用）
3. **Patrol wizard input mapping 改成 Option 2+3**（顯式表單 + 慣例自動填）

---

## 1. Architecture & Design

### 1.1 Event Registry attribute schema

#### DB schema 改動

`event_types` 表加欄：
```sql
ALTER TABLE event_types ADD COLUMN attributes JSONB NOT NULL DEFAULT '[]'::jsonb;
```

`attributes` 是 list of attribute spec：
```json
[
  {"name": "equipment_id", "type": "string", "required": true,  "description": "發生事件的機台 ID"},
  {"name": "step",         "type": "string", "required": true,  "description": "事件發生時的 step"},
  {"name": "lot_id",       "type": "string", "required": false, "description": "受影響的 lot"},
  {"name": "spc_chart",    "type": "string", "required": false,
   "enum": ["xbar","r","s","p","c"], "description": "OOC 落在哪張 chart"}
]
```

支援 `type`：`string` / `number` / `boolean`（v1 只做這三個，v2 再考慮 `array` / `object`）。

#### Frontend：Event Registry 編輯 UI

`/system/event-registry` 頁面 + 新建/編輯 modal：
- 既有欄位：name、severity、description
- **新增 attribute table**：每列 `name | type | required | enum (optional) | description`
- 「+ 加欄位」按鈕、刪除個別 attribute
- 預設：新建 event 自動帶 `equipment_id` + `step`（其他自填）

#### Backend：API
- `POST /api/v1/system/event-types`：含 attributes
- `PUT  /api/v1/system/event-types/{id}`：修改 attribute（注意：已綁 patrol 的 event 改 attribute 要警告）
- `GET  /api/v1/system/event-types`：list（patrol wizard 拉這個給 dropdown）

---

### 1.2 Patrol wizard Step 2 — Scope 選擇器

事件觸發 → **跳過 scope（自動 = 觸發事件的單一 equipment_id）**

排程觸發 / 指定時間 → 顯示 scope 三選項：

| 選項 | UI | 內部展開邏輯 |
|---|---|---|
| **所有機台** | radio 「☑ 全部 (上限 N 台)」 | trigger 時抓 simulator `/api/v1/equipment` 全 list，截斷到 cap |
| **指定機台** | chips multi-select：`☐ EQP-01 ☐ EQP-02 ...` | list 直接照給 |
| **指定站點** | dropdown 選 step：`STEP_001 ▼` | trigger 時抓 simulator 該 step 的 tool list，截斷到 cap |

**Cap（你決策 #2）**：
- 系統 parameter `MAX_PATROL_FANOUT` 預設 **20**
- patrol 自己也可以 override（進階設定，UI 預設不顯示，cron expr 旁的「⚙ 進階」展開）
- 超 cap 時：執行只跑前 N 台、log warning + 寫 alarm「scope 截斷 from M to N」讓 user 知情

#### DB schema for `auto_patrols.target_scope`

```jsonc
// Event-triggered (no scope needed; equipment_id from event):
{ "type": "event_driven" }

// All equipment, capped:
{ "type": "all_equipment", "fanout_cap": 20 }

// Specific equipment list:
{ "type": "specific_equipment", "equipment_ids": ["EQP-01", "EQP-03"] }

// By step:
{ "type": "by_step", "step": "STEP_001", "fanout_cap": 20 }
```

---

### 1.3 Patrol wizard Step 3 — Input Mapping (Option 2+3)

每個 pipeline.input 都渲染成一列（**Option 2 strict form**），但**初始值用 Option 3 慣例自動填**，user 想改就改。

#### Wizard 渲染流程
1. Wizard fetch 該 pipeline 的 `inputs[]` declaration
2. Wizard fetch event_type 的 `attributes[]`（事件觸發時）
3. 套**慣例表**自動配 binding（見下表）
4. 渲染表單，每列：`label | source dropdown | value field`

#### 慣例對映表（Option 3 — 自動配）

| Pipeline input name (常見) | Event 觸發 auto-bind | Schedule/Once 觸發 auto-bind |
|---|---|---|
| `tool_id`, `equipment_id` | `$event.equipment_id` | `$loop.tool_id` |
| `step`, `step_id` | `$event.step` | `$loop.step` (僅 by_step scope) |
| `lot_id` | `$event.lot_id`（如該 event 有此 attribute） | (無 — user 自填) |
| `since`, `time_range` | (use pipeline default) | (use pipeline default) |
| `severity` | `$event.severity` | (literal — user 填) |
| 其他自定義名 | (無 — user 自填) | (無 — user 自填) |

#### Source dropdown 選項

| Source | 例 | 適用 trigger |
|---|---|---|
| 事件屬性 | `$event.equipment_id` | event |
| 迴圈展開值 | `$loop.tool_id`, `$loop.step` | schedule/once |
| 字面值 | `"EQP-07"`、`24` | 任何 |
| Pipeline 預設值 | (略過此欄，pipeline 用 `default`) | 任何 |
| 表達式（v2） | `$now() - 24h` | (v1 不支援) |

#### Validation @ save
- 每個 pipeline.input 中 `required: true` 的，必須有非空 source
- `string` type 不能配 `number` source
- 事件觸發但 binding 用 `$loop.X` → reject
- 排程觸發但 binding 用 `$event.X` → reject

#### UI mock

```
┌─ 設定 Auto-Patrol Inputs · Step 3/3 ─────────────────────┐
│  Pipeline #5 [migrated] Same APC check 需要 1 個 input：  │
│                                                            │
│  tool_id (string, required)                                │
│  ╭────────────────────────────────────────────────────╮   │
│  │ 來源： [ $event.equipment_id ▼ ]   ✓ 自動帶入       │   │
│  │ 預覽： event 觸發時，equipment_id=EQP-07 → tool_id │   │
│  ╰────────────────────────────────────────────────────╯   │
│                                                            │
│  [← 返回]                              [儲存 Patrol]       │
└────────────────────────────────────────────────────────────┘
```

---

### 1.4 Backend 執行邏輯

#### Event-triggered patrol
1. Event 進來（payload `{equipment_id, step, lot_id, ...}`）
2. AutoPatrolService 找 `trigger_mode='event' AND event_type_id=X` 的 active patrols
3. 對每個 patrol：
   - Render `input_binding` 模板：`{"tool_id": "$event.equipment_id"}` → `{"tool_id": "EQP-07"}`
   - Call pipeline executor with that input
   - 結果 → alarm（如有 trigger）

#### Schedule / Once patrol
1. Cron 觸發（沒 payload）
2. 依 `target_scope.type` 展開 loop iterations：
   - `all_equipment`: 抓 simulator tool list、cap 到 fanout_cap
   - `specific_equipment`: 直接用 list
   - `by_step`: 抓 simulator 該 step 的 tools、cap
3. 對每個 iteration：
   - Build context `{loop: {tool_id: "EQP-01"}}` (or `{loop: {step: "STEP_001"}}`)
   - Render `input_binding` 模板
   - Call pipeline executor
   - 結果 → alarm（如有 trigger）
4. 全部跑完 emit 一個 patrol_run 的彙總 log

#### `input_binding` 模板 render

簡單 Pythonish：
```python
def render(template: dict, context: dict) -> dict:
    """Replace $event.X / $loop.X / literal."""
    out = {}
    for k, v in template.items():
        if isinstance(v, str) and v.startswith("$"):
            # e.g. "$event.equipment_id" → context["event"]["equipment_id"]
            parts = v[1:].split(".")
            cur = context
            for p in parts:
                cur = cur.get(p) if isinstance(cur, dict) else None
                if cur is None: break
            out[k] = cur
        else:
            out[k] = v  # literal
    return out
```

---

## 2. Step-by-Step Execution Plan

| Order | Item | Effort | Dep |
|---|---|---|---|
| 1 | DB migration: `event_types.attributes` JSONB | 0.1 day | none |
| 2 | Backend Event Type CRUD with attributes | 0.3 day | (1) |
| 3 | Frontend Event Registry attribute editor | 0.5 day | (2) |
| 4 | DB migration: `auto_patrols.target_scope` 規範化 (string/JSONB 統一格式) | 0.1 day | none |
| 5 | Patrol wizard Step 2 加 scope selector | 0.4 day | (4) |
| 6 | Patrol wizard Step 3 input mapping 表單 | 0.6 day | (3)(5) |
| 7 | Backend AutoPatrolService 解析 target_scope + render input_binding | 0.5 day | (5) |
| 8 | Backend MAX_PATROL_FANOUT cap + warning log | 0.2 day | (7) |
| 9 | Test: event-triggered + schedule all_equipment + schedule by_step + once specific | 0.4 day | all |

**總共 3.1 day**。

---

## 3. Edge Cases & Risks

| Risk | 嚴重 | Mitigation |
|---|---|---|
| 改 Event attribute schema 破壞已綁 patrol | 🔴 High | save 時警告：「N 個 patrol 用此 event，改 attribute 會讓 binding 失效」+ require confirm |
| 簡擬器 1000 台 + all_equipment + 1 hour cron = 1000 run/hr | 🔴 High | MAX_PATROL_FANOUT cap (default 20)，超出 log warn + alarm |
| Pipeline.inputs 改了（rename / 新增 required）導致已存 binding 失效 | 🟡 Med | patrol 開啟時 re-validate against pipeline 最新 inputs，若 mismatch 顯示 ⚠ 並 disable until user 修 |
| 約定表慣例對 user 不直覺（e.g. user 預期 `tool_id` 是 literal 不是 `$event.equipment_id`） | 🟡 Med | 「自動帶入」旁邊放小灰字「(改成 literal)」可一鍵切；UI tooltip 解釋慣例 |
| `$event.X` 抓不到（event 沒這 attribute） | 🟡 Med | save validation 檢查；trigger 時若 attribute null → warn alarm + skip pipeline run |
| `by_step` scope simulator 抓 tools 失敗 | 🟢 Low | timeout + retry + skip iteration log warn |
| Once trigger 已過時間還沒跑 | 🟢 Low | trigger UI hint：「指定時間需在未來」+ scheduler 啟動時清掉過期 once |

---

## 4. Open Questions

1. **MAX_PATROL_FANOUT 預設值**：20 / 50 / 100？影響取決於 production 機台數；先 20 安全起見
2. **Event attribute type 系統**：v1 只支援 string / number / boolean。`enum` 是 string 子類。要不要支援 `datetime`？（建議 v2）
3. **Schedule scope = 站點 + 所有機台 互斥**？還是 step + filter (e.g., 「STEP_001 的 EQP-01 ~ 03」)？(v1 互斥，v2 加交集)
4. **`input_binding` template 是否支援 transform**（e.g. `$event.equipment_id.upper()`）？v1 純 lookup，v2 看需求加 jq / jsonpath
5. **既有 6 個已綁 patrol 怎麼辦**？（剛才砍光了，所以這題消滅 ✓）
6. **Pipeline default value vs patrol input_binding 優先**：建議 patrol 設了就 override pipeline default；patrol 沒設就用 pipeline default
7. **Event Type 嚴重性能 mapping 進 alarm**？（事件 severity=WARNING，alarm 預設也 WARNING 還是看 pipeline 的 alert block）— 建議 pipeline 的 block_alert.severity 為主，event severity 只在 patrol UI 預覽用

---

## 1.5 — Agent ↔ Pipeline Inputs Coupling (補 2026-04-28)

### 問題

User 在 wizard 宣告 `$equipment_id`（example=EQP-01），然後 agent build → agent 把 user prompt 裡的「EQP-01」**寫死成 literal** `tool_id="EQP-01"`，沒有用 `$equipment_id` 引用。Run 時 user 填 EQP-05 → pipeline 還是查 EQP-01。

Root cause：
- `agent_builder/orchestrator.py` 的 `build_system_prompt(registry)` 只 inject block catalog + 規則，**沒讀** `session.pipeline_json.inputs`
- 即使 user prompt 提到 EQP-01 / STEP_001 / LOT-X 這類**實例值**，agent 沒被指示「這應該是變數」
- agent 的 toolset 沒有 `declare_input` — 即使想自己宣告也辦不到

### 三層方案（合做）

| 方案 | 角色 | 實作 |
|---|---|---|
| **Option 1**（主要）| 「**用 user 已宣告的 inputs**」 | orchestrator inject `Pipeline 已宣告 inputs: ...` 進 user opening message；prompt.py 加硬規則「凡 source block param 對應已宣告 input → 必寫 `$name`，不寫 literal」 |
| **Option 2**（兜底）| 「**Agent 自己宣告**」 | 新 `declare_input` tool；prompt.py 規則：「user prompt 裡的 EQP-XX / STEP_XXX / LOT-XXX / lot_id 要先 `declare_input` 再 `$name` 引用」 |
| **Option 3**（救火）| 「**Inspector 自動偵測 + 一鍵綁**」 | Pipeline 已存在但 param 是 literal 時，UI 偵測 input.example 跟 param 值一樣 → 顯示 [⚡ 綁定] 按鈕 |

### 實作 Option 1+2

#### `agent_builder/orchestrator.py`
在 `stream_agent_build()` build initial messages 前，組一段 inputs context 注入 user opening：

```python
inputs_hint = ""
declared = session.pipeline_json.inputs or []
if declared:
    lines = [f"  - $「{i.name}」({i.type}{', required' if i.required else ''}, example={i.example})"
             for i in declared]
    inputs_hint = (
        "\n\n# Pipeline 已宣告的 inputs（你必須引用這些變數而非寫死字面值）：\n"
        + "\n".join(lines)
        + "\n\n⚠ 凡 source / filter block 的 param 值對應上述 input 時（如 tool_id、step、lot_id），"
        "**必寫 `$name`，禁寫 literal**。否則 pipeline 無法被 patrol 重複用。"
    )
user_opening = session.user_prompt + inputs_hint
```

#### `agent_builder/tools.py` 新增 `declare_input`
```python
async def declare_input(
    self, name: str, type: str = "string", required: bool = True,
    example: Optional[str] = None, description: str = "",
) -> dict[str, Any]:
    """Add a `$<name>` input variable to pipeline_json.inputs."""
    # validation: name unique, type ∈ {string, number, boolean}
    # mutate session.pipeline_json.inputs
```

#### `agent_builder/prompt.py` 加變數使用規則
- 「Variable extraction rule」段：規範 instance-like 值（EQP-XX、STEP_XXX、LOT-XXX）→ 必先 declare_input
- 「Pipeline.inputs awareness rule」段：source / filter 的 param 對應已宣告 input → 必用 `$name`
- 在 Pattern A-D 的範例裡加上一條「Pattern 0：input declaration first」

### Effort

- orchestrator.py inject inputs context：0.1 day
- declare_input tool：0.15 day
- prompt.py rules + example：0.15 day
- Test (no inputs / 1 input / 2 inputs / agent self-declare path)：0.1 day

**總共 0.5 day**。

### Edge Cases

- User 宣告了 input 但 agent 還是寫 literal（LLM 偶爾不聽話）→ validate() tool 加檢查：若 input 已宣告但無任何 node param 引用 `$name`，回 warning（不阻塞 finish）
- User 沒宣告 input + agent 自己 declare 多餘的 → finish 時 cull 沒被 node 引用的 inputs（避免 wizard 顯示沒用的變數）
- 同名衝突（user 宣告 `equipment_id`，agent 又 declare `equipment_id`）→ declare_input idempotent，已存在就更新 example/description 不報錯

---

## 5. UX Examples

### Example A: 「OOC event 一發生，跑 SPC 檢查」
- Event Registry：`OOC` 加 attribute `equipment_id, step, lot_id, spc_chart`
- Patrol Step 1：trigger=event, event_type=OOC
- Patrol Step 2：(scope 自動 = 觸發事件的單機台，跳過此頁)
- Patrol Step 3：pipeline 需要 `tool_id, step` → 自動配 `$event.equipment_id, $event.step`
- 結果：每次 OOC 觸發、跑一次 pipeline、產一個 alarm

### Example B: 「每天凌晨 3 點，巡所有機台 recipe 一致性」
- Patrol Step 1：trigger=schedule, cron=`0 3 * * *`
- Patrol Step 2：scope=`all_equipment, fanout_cap=20`
- Patrol Step 3：pipeline 需要 `tool_id` → 自動配 `$loop.tool_id`
- 結果：每天 03:00 抓 simulator tool list（cap 20）、跑 20 次 pipeline、產 0~20 個 alarm

### Example C: 「STEP_001 站點下午 4 點巡一次」
- Patrol Step 1：trigger=once, datetime=2026-04-29T16:00
- Patrol Step 2：scope=`by_step, step=STEP_001, fanout_cap=20`
- Patrol Step 3：pipeline 需要 `tool_id, step` → 自動配 `$loop.tool_id, $loop.step`
- 結果：4 點抓 STEP_001 的 tools（cap 20）、跑 N 次、跑完自動 inactive

---

請 review。確認 OK 回「開始開發」我按 §2 順序動手。沒問題的話，建議**先做 §1.1 Event Registry**（其他兩個 step 都依賴 attribute schema），再做 §1.2 + §1.3。
