# Tech Spec: AIOps Knowledge Studio — Skill Designer v2.0
**Version:** v2.0 (Approved)
**Status:** ✅ Implementation Started
**Date:** 2026-03-28

---

## 1. Context & Objective

重建 Skill Builder，引入三個核心設計：

1. **Python Steps Mapping** — LLM 把自然語言拆解成多個 step，每個 step 對應一段 Python code，前端雙向 Highlight
2. **System Event / Alarm 明確分層** — System Event 是 Ontology Simulator 發出的原始事件（唯讀）；Alarm 是 Skill 偵測到異常後主動建立的通知，有生命週期
3. **Alarm-Centric 首頁** — 首頁主體從機台狀態切換到 Alarm 列表

---

## 2. 三層角色設計

```
System Admin  →  定義 System Event Catalog（SPC_OOC 的 schema、來源）
Super User    →  用 System Event 設計 Skill（NL → Python Steps）
All Users     →  看 Alarm 首頁，處理告警
```

---

## 3. System Event Catalog（Admin 管理）

**Table: `event_types`**（擴充現有表）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK | |
| name | TEXT UNIQUE | `"SPC_OOC"` |
| description | TEXT | |
| source | TEXT | `"simulator"` / `"webhook"` / `"manual"` |
| is_active | BOOLEAN | Admin 可停用某事件類型 |
| attributes | TEXT | JSON（保留向後相容，v18 不再使用） |
| created_at / updated_at | DATETIME | |

### Standard Event Payload（所有 System Event 共用）

```json
{
  "event_type":   "SPC_OOC",
  "equipment_id": "EQP-01",
  "lot_id":       "LOT-0001",
  "step":         "STEP_091",
  "event_time":   "2026-03-28T01:06:05Z"
}
```

> 這 5 個欄位足以透過 Ontology MCP 追蹤所有相關 object（DC / SPC / APC / RECIPE 全部）。

---

## 4. Skill 資料結構（重建）

**Table: `skill_definitions`**（DROP 舊表，重建）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK | |
| name | TEXT UNIQUE | |
| description | TEXT | |
| trigger_event_id | FK → event_types | NULL = 僅支援排程觸發 |
| trigger_mode | TEXT | `"schedule"` / `"event"` / `"both"` |
| steps_mapping | TEXT (JSON) | `[{step_id, nl_segment, python_code}]` |
| visibility | TEXT | `"private"` / `"public"` |
| created_by | FK → users | |
| created_at / updated_at | DATETIME | |

### steps_mapping JSON 格式

```json
[
  {
    "step_id": "step1",
    "nl_segment": "查 DC 快照，找出異常感測器",
    "python_code": "dc = await execute_mcp('get_process_context', {'targetID': lot_id, 'step': step, 'objectName': 'DC'})\nsensor_vals = dc.get('parameters', {})"
  },
  {
    "step_id": "step2",
    "nl_segment": "若 chamber_pressure 超出 UCL 17.5，發出告警",
    "python_code": "if sensor_vals.get('chamber_pressure', 0) > 17.5:\n    trigger_alarm(severity='HIGH', title='Chamber Pressure OOC')"
  }
]
```

### `trigger_alarm()` Severity 選項

```python
# 選項：LOW / MEDIUM / HIGH / CRITICAL
trigger_alarm(severity='HIGH', title='Chamber Pressure OOC', summary='sensor_01 = 18.3，超出 UCL 17.5')
```

---

## 5. 分層設計：System Event vs Alarm

| | System Event | Alarm |
|---|---|---|
| 來源 | OntologySimulator（唯讀 API） | 我們的 `alarms` 表 |
| 存儲 | **不存 DB**，on-demand query | **存 DB**，有生命週期 |
| 觸發 | 由 Simulator 的製程狀態產生 | 由 Skill 執行 ABNORMAL 後建立 |
| 代表意義 | 「發生了什麼」 | 「需要人處理什麼」 |
| 範例 | SPC_OOC、ProcessEnd | "EQP-01 連續 3 次 OOC 需檢修" |

---

## 6. Alarm 資料結構（新建）

**Table: `alarms`**（取代 `generated_events`，DROP 舊表）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | PK | |
| skill_id | FK → skill_definitions | 哪個 Skill 觸發 |
| trigger_event | TEXT | 事件類型（冗餘存，for query） |
| equipment_id | TEXT | indexed |
| lot_id | TEXT | indexed |
| step | TEXT | |
| event_time | DATETIME | 事件發生時間（Ontology 時間） |
| severity | TEXT | `LOW/MEDIUM/HIGH/CRITICAL` |
| title | TEXT | Skill 決定的簡短標題 |
| summary | TEXT | 詳細說明 |
| status | TEXT | `active/acknowledged/resolved` |
| acknowledged_by | TEXT | nullable |
| acknowledged_at | DATETIME | nullable |
| resolved_at | DATETIME | nullable |
| created_at | DATETIME | |

---

## 7. 雙觸發機制

```
trigger_mode = 'event'    → 收到 System Event 時執行
trigger_mode = 'schedule' → RoutineCheck 排程定期執行
trigger_mode = 'both'     → 兩者都觸發
```

**Event-Driven 執行流（現階段 Simulator）：**
```
Backend 定期 poll OntologySimulator /api/v1/events
  → 偵測到 SPC_OOC 新事件
  → 查找 trigger_event_id 符合且 is_active 的 Skills
  → 注入 standard_payload，沙盒執行 steps
  → trigger_alarm() → 寫 alarms 表
```

**未來外部對接：** `POST /api/v1/system-events/ingest` webhook endpoint。

---

## 8. Alarm-Centric 首頁

```
┌─────────────────────────────────────────────────┐
│  🔴 CRITICAL: 1   🟠 HIGH: 3   🟡 MEDIUM: 5    │  ← Severity Badge Bar
├─────────────────────────────────────────────────┤
│  Active Alarms                         [篩選 ▼] │
│  EQP-01 | LOT-0001 @ STEP_091                   │
│  Chamber Pressure OOC  · 5分鐘前 · [認領] [解決]│
├─────────────────────────────────────────────────┤
│  機台狀態（折疊，次要）                         │
└─────────────────────────────────────────────────┘
```

---

## 9. API Endpoints

### Skills
- `GET  /api/v1/skill-definitions` — list
- `POST /api/v1/skill-definitions` — create
- `GET  /api/v1/skill-definitions/{id}` — get
- `PATCH /api/v1/skill-definitions/{id}` — update
- `DELETE /api/v1/skill-definitions/{id}` — delete
- `POST /api/v1/skill-definitions/generate-steps` — LLM generates steps_mapping from NL
- `POST /api/v1/skill-definitions/{id}/try-run` — sandbox try-run with mock payload
- `POST /api/v1/skill-definitions/{id}/execute` — real execution with event payload

### Alarms
- `GET  /api/v1/alarms` — list (filters: severity, status, equipment_id, days)
- `GET  /api/v1/alarms/stats` — count by severity (for homepage badge bar)
- `GET  /api/v1/alarms/{id}` — get
- `PATCH /api/v1/alarms/{id}/acknowledge` — acknowledge
- `PATCH /api/v1/alarms/{id}/resolve` — resolve

### System Events (webhook ingest, future)
- `POST /api/v1/system-events/ingest` — external event push

---

## 10. Execution Plan

| Phase | 工作項目 | 狀態 |
|-------|----------|------|
| 1 | DB 重建：event_types 擴充，skill_definitions 重建，alarms 新建 | ✅ Done |
| 2 | Backend：AlarmService + SkillExecutorService + Routers + Wire-up | ✅ Done |
| 3 | Backend：LLM steps_mapping 生成（generate-steps endpoint） | ✅ Done |
| 4 | Backend：Event-Driven poller（Simulator）+ webhook ingest | ✅ Done |
| 5 | Frontend：Skill Builder 雙欄 UI + 雙向 Highlight + Try-Run | ✅ Done |
| 6 | Frontend：Alarm 首頁（Severity Badge Bar + Active List + 認領/解決） | ✅ Done |

---

## 11. Edge Cases & Risks

| 風險 | 處理 |
|------|------|
| `trigger_alarm()` 在 Python 沙盒裡 | Sandbox context 注入，不 import，攔截並寫入 alarms 表 |
| 沙盒 execute_mcp 是 async | Skill executor 本身是 async，直接 await |
| Skill 執行超時 | asyncio.wait_for 30s 上限 |
| 惡意程式碼注入 | 靜態 pattern scan：ban os/sys/open/exec/eval/subprocess |
| Alarm 大量 | pagination + 預設只顯示近 7 天 active |
| `event_time` 一致性 | Ontology 事件時間 vs alarm 建立時間分開存 |
