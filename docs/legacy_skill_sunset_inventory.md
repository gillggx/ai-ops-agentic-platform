# Legacy Skill Model — Sunset Inventory

> 盤點日期：2026-06-29。目標：只留 skills_v2，移除 legacy skill_documents
> 模型的 data / code / schema。**先補功能 → 建 branch → 分階段砍。**

## ✅ 狀態：完成（2026-06-29）

全部 phase 已執行 + 驗證（branch `legacy-skill-sunset`）：
- 補功能：v2 raw-event 觸發，重建 legacy 115（OOC 自動診斷 → skills_v2 id 18）
- Phase 1：停 legacy schedule + event 觸發
- Phase 2：PatrolActivity / AlarmEnrich / Handoff / scheduler 改讀 skills_v2
- Phase 3：刪 9 個 legacy 檔（SkillDocument*/Runner/Step/Materialize/AlarmEmitter/Dtos）
- Phase 4：V68 — 刪 20,826 筆 legacy 歷史 + drop skill_documents/skill_stages
  + 拆 5 條 FK + 移除 skill_runs.skill_id 欄

**執行中修正的兩個誤判（原盤點寫錯，實際保留）：**
- ❗ **SkillDefinition*（skill_definitions）保留** — 是獨立 registry，sidecar
  internal skill lookup + system monitor 還在用。**不是** skill_documents 模型。
- ❗ **auto_patrols 保留** — 獨立的 user-rules / patrol 機制，仍 wired
  （MonitorController / UserRulesController / EventDispatchService 等）。
  只拆掉它指向 skill_documents 的 FK。

下面是原始盤點（保留供參考，部分已被上面修正取代）。

---

## 0. TL;DR

- Legacy 有 **2 個還在跑的 patrol**（43 schedule、115 event），都不是 v2 的精確重複。
- 砍之前 v2 有 **2 個功能缺口**必須補：**raw-event 觸發**、**suggested_actions/halt**。
- `skill_runs`（20,818 列）**v2 也在用** — 不能整張刪，只能拆 legacy 欄位。
- **5 條 FK** 指向 `skill_documents`，drop 前要逐一處理。
- 多個**共用 consumer**（patrol-activity 頁、alarm 詳情、handoff）讀 legacy — 砍前要 rewire。

---

## 1. 還在跑的 Legacy Patrol

| id | slug | 觸發 | 24h 次數 | pipeline | 特性 |
|---|---|---|---|---|---|
| 43 | hourly-eqp-5in3out-check | schedule hourly | 24 | 73 | 「5 取 3 out」+ suggested_actions（禁用該機台） |
| 115 | event-ooc-diagnose-eqp-process | **event: OOC（raw）** | **429** | 73 | OOC 事件觸發診斷 + suggested_actions |

其餘 4 個 skill_documents 是 `draft`（沒在跑）。

### 跟 v2 的對照
| Legacy | v2 對應 | 差異 |
|---|---|---|
| 43「5 in 3 out」schedule | id 11「5 in 2 out」schedule | **門檻不同（3 vs 2）** |
| 115「OOC raw event 診斷」 | **無** | v2 沒有 raw-event patrol |

---

## 2. v2 功能缺口（砍之前要補）

### 缺口 A — Raw-event 觸發（blocker，replace 115 必需）
- **Legacy**：`EventPollerService`（poll simulator）→ `dispatchGeneratedEvent(event_type_id)` →
  `dispatchToSkillsByEvent` 比對 `skill_documents.trigger_config.event == event_type.name`。
  即「raw simulator 事件（OOC / FDC_FAULT…）直接觸發 skill」。
- **v2 現況**：我建的 event 只支援「**上游 v2 patrol 出 alarm 時**觸發」
  （`fanOutToEventSubscribers`，source = upstream slug）。**不吃 raw event。**
- **要補**：v2 event trigger 增加一種 source 型別 `raw_event`，例如
  `{"kind":"event","source_type":"raw_event","event":"OOC"}`，
  讓 `EventPollerService` / `dispatchGeneratedEvent` 也掃 skills_v2 並 fire v2 runner。
- **可用的 raw event_types**（12 個）：OOC, SPC_OOC_Etch_CD, FDC_FAULT, FDC_WARNING,
  PM_START, PM_DONE, EQUIPMENT_HOLD, RECIPE_VERSION_BUMP, APC_AUTO_CORRECT,
  ENGINEER_OVERRIDE …

### 缺口 B — suggested_actions / halt
- **Legacy**：step 帶 `suggested_actions:[{text:"禁用該機台", halt:false}]`
  — alarm 卡上給 operator 的建議動作 + 是否 halt 機台。
- **v2 現況**：只有 `alarm_gate` / `outcome` 字串，沒有結構化 suggested-actions。
- **決策**：
  - (B1) **港過來**：skills_v2 加 `suggested_actions` 欄（JSON），alarm emit 時帶上。
  - (B2) **放棄**：v2 模型刻意更簡單，suggested-actions 不做（operator 自己判斷）。
  - 建議先問 user 這功能有沒有在用；沒人用就 B2。

---

## 3. 移除範圍 — Code（~30+ 檔）

### 可直接刪（legacy-only，無 v2 共用）
```
api/skill/SkillDocumentController.java
api/skill/SkillDocumentService.java
api/skill/SkillRunnerService.java        (step-based runner)
api/skill/SkillStepExecutor.java
api/skill/SkillMaterializeService.java
api/skill/SkillAlarmEmitter.java         (legacy alarm emit；v2 用 SkillV2RunnerService)
api/skill/SkillDefinitionController.java
api/skill/SkillDefinitionsAliasController.java
api/skill/SkillDefinition*  (entity/repo — 0 rows)
api/skill/Dtos.java, package-info.java
domain/skill/SkillDocumentEntity.java + Repository
scheduler/patrol/SkillScheduleService.java  → 移除 legacy tick() loop（保留 tickV2）
scheduler/patrol/EventDispatchService.java   → 移除 dispatchToSkillsByEvent（skill_documents 段）
scheduler/patrol/AutoPatrolExecutor.java     (auto_patrols 0 rows — 確認後刪)
```

### 共用 / 要 rewire（不能直接刪）
```
domain/skill/SkillRunEntity.java + Repository   → v2 也用；移除 skillId 欄 + legacy query
api/patrol/PatrolActivityController/Service       → 改讀 skill_v2_id（漏斗頁）
api/alarm/AlarmEnrichmentService                  → alarm 詳情讀 legacy skill → 改 v2 或拔
api/handoff/HandoffService                        → 確認是否依賴 legacy skill
domain/alarm/AlarmEntity.skillId                  → 評估是否還需要（v2 用 skill_run_id）
api/internal/InternalSkillController              → 移除 legacy by-slug/run-system，保留 v2/{id}/run-system
```

---

## 4. 移除範圍 — Schema

### Tables（legacy 專屬）
| table | rows | 處置 |
|---|---|---|
| skill_documents | 6 | drop（先處理 5 條 FK） |
| skill_definitions | 0 | drop |
| auto_patrols | 0 | drop |
| pb_published_skills | 0 | drop（chat search 已改 union skills_v2，但 0 rows 可留可刪） |
| skill_stages | ? | drop（V65 已 sunset，確認空） |

### 指向 skill_documents 的 5 條 FK（drop 前處理）
| table.column | 處置 |
|---|---|
| `skill_runs.skill_id` | 移除欄 + FK（v2 用 skill_v2_id）；歷史 legacy run 要不要保留？見下 |
| `auto_patrols.skill_doc_id` | 表會被 drop |
| `pipeline_auto_check_triggers.skill_doc_id` | nullable 化或 drop trigger 表 legacy 欄 |
| `pb_pipelines.parent_skill_doc_id` | set null（pb_pipelines 保留） |
| `skill_stages.skill_doc_id` | 表會被 drop |

### `skill_runs` 歷史資料決策
- 20,818 列，大多是 legacy（skill_id）。
- (a) **保留歷史**：留 skill_id 欄當 nullable、移除 FK，不刪舊 run（patrol-activity 可看歷史）。
- (b) **清乾淨**：刪所有 skill_id IS NOT NULL 的 run，移除 skill_id 欄。
- 建議 (a) — 砍 FK 不砍資料，避免弄丟稽核軌跡。

---

## 5. 共用 Consumer 影響（rewire 清單）

| Consumer | 現在讀 | 砍後要 |
|---|---|---|
| patrol-activity 漏斗頁 | skill_runs.skill_id + skill_documents | 改讀 skill_v2_id + skills_v2 |
| alarm 詳情 / AlarmEnrichmentService | alarm.skill_id → skill_documents | 改用 alarm.skill_run_id → skill_runs.skill_v2_id |
| handoff | 待確認 | 待查 |

---

## 6. 執行計畫（補功能 → branch → 分階段砍）

### Step 0（現在）— 補功能（在現有 branch 或新 feature 分支）
- [ ] 補缺口 A：v2 raw-event trigger（讓 v2 能 replace 115）
- [ ] 決定缺口 B：suggested_actions 港 or 放棄
- [ ] 在 v2 重建 115 等價（raw OOC event → 診斷 pipeline 73 邏輯），啟用 + 驗證跑得起來
- [ ] （可選）在 v2 重建 43 等價，或確認 11 取代它（門檻 2 vs 3 要 user 確認）

### Step 1 — 建 sunset branch
- `git checkout -b legacy-skill-sunset`（從補完功能的點切）

### Step 2 — 分階段砍（每階段 deploy + 驗證）
1. **停 legacy 觸發**：scheduler 移除 legacy tick/event 段 + skill_documents 設 inactive
2. **rewire consumer**：patrol-activity / alarm-enrich / handoff 改讀 v2
3. **移除 legacy code**：30+ 檔
4. **schema**：處理 5 FK → drop legacy 表 + 拆 skill_runs.skill_id

---

## 7. 待 user 拍板

1. **缺口 B（suggested_actions / 禁用該機台）** — 港過來 or 放棄？
2. **43（5in3out）** — v2 的 11（5in2out）取代它即可（接受門檻變 2），還是要在 v2 另建一個 5in3out？
3. **skill_runs 歷史** — 保留（砍 FK 不砍資料）or 清乾淨？
4. 補完功能後再砍，確認這個順序。
