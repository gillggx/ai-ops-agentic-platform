# Unified Skill Model — Spec (v30.17 draft, 2026-05-17)

> 取代散落的 auto_patrol / auto_check / pipeline_auto_check_triggers / RoutineCheck
> 多套概念，以 `hourly-eqp-5in3out-check` 為範本，把「定/事件觸發 + 可選 alarm
> gate + 深度診斷 checklist」收斂成一個 SkillDocument。

## 1. Context & Objective

Phase 11 之前曾有 auto_patrol (排程巡檢) 與 auto_check (alarm 觸發後深度分析)
兩個獨立的 entity + scheduler 路徑。隨 Skill 11 引入 SkillDocument，這兩個
概念事實上已能用 `skill.confirm_check` (= alarm gate) 與 `skill.steps` (=
checklist) 表達，但程式還保有舊路徑與舊表，造成:

- DB 有 3+ 個過時表 (auto_patrols / pipeline_auto_check_triggers / routine_checks)
- AlarmEnrichmentService 既看 execution_log 又看 pb_pipeline_runs (雙路徑)
- Frontend Alarm Detail 同時 render `autoCheckRuns / diagnostic_data_views / trigger_data_views`
- 新建 SkillRunner emit 路徑 (v30.13~16) 因為 legacy 還在，需要相容兩邊

統一後: **一個 SkillDocument 就是完整的「觀察 + 判定 + 診斷」**，trigger 走 schedule
或 event，gate 過了就 emit alarm + 深度診斷一起入庫。

## 2. 用詞釐清

| 詞 | 程式欄位 | 角色 | 必要性 |
|---|---|---|---|
| Trigger | `skill.trigger_config.type ∈ {schedule, event}` | 啟動條件 | 必要 |
| **Alarm Gate** (舊稱 confirm_check / auto-patrol C1) | `skill.confirm_check` | 判定「真的有問題嗎」| **Optional** |
| **Checklist** (舊稱 auto-check) | `skill.steps[]` | 深度診斷 | 至少 1 step |

## 3. 流程 (兩 mode)

### Mode A — Timer (`trigger.type = "schedule"`)
```
cron tick (依 schedule.mode)
   ↓
SkillRunnerService.run(slug, payload={})
   ↓
[ if skill.confirm_check 存在 ]
   run alarm gate
     ├─ fail → skipped_by_confirm
     │         write execution_log {condition_met:false}
     │         DO NOT emit alarm
     │         DONE
     └─ pass ↓
   ↓
run all checklist steps
   ↓
emit alarm:
  trigger_reason = {source:"schedule", gate:{note,value,operator,threshold,data_views}}
  deep_diagnostic = {steps:[{step_id,name,status,note,data_views,charts?}]}
write execution_log + alarm.execution_log_id 指過去
```

### Mode B — Event (`trigger.type = "event"`)
```
generated_events INSERT (e.g. OOC) — by EventPoller
   ↓
EventDispatchService:
   query skill_documents WHERE trigger_config->>'type'='event'
                          AND trigger_config->>'event'=<event_type>
   (+ optional match_filter on event payload e.g. equipment)
   ↓
for each matched skill:
   SkillRunnerService.run(slug, payload=event_mapped_params)
     ↓
   *** skip alarm gate (event 本身即是 alarm) ***
     ↓
   run all checklist steps
     ↓
   emit alarm (一定 emit):
     trigger_reason = {source:"event", event_type, event_time, event_payload}
     deep_diagnostic = {steps:[...]}
```

## 4. trigger_reason 欄位 schema

`trigger_reason` ＝「為何 emit 這個 alarm」的證據。儲在
`execution_log.llm_readable_data.trigger_reason`，UI 觸發原因 section 直接讀。

### Mode A (schedule + gate pass)
```json
{
  "source": "schedule",
  "schedule": {"mode": "hourly", "every": 1},
  "fired_at": "2026-05-17T01:00:00Z",
  "gate": {
    "pipeline_id": 72,
    "note": "2.0 >= 2.0",
    "value": 2.0, "operator": ">=", "threshold": 2.0,
    "data_views": [...]   // gate 看到的 evidence rows
  }
}
```

### Mode A (schedule, no gate configured)
```json
{
  "source": "schedule",
  "schedule": {"mode": "hourly", "every": 1},
  "fired_at": "2026-05-17T01:00:00Z",
  "gate": null,
  "note": "No alarm gate configured — proceeded directly to checklist."
}
```

### Mode B (event)
```json
{
  "source": "event",
  "event_type": "OOC",
  "event_time": "2026-05-17T01:00:00Z",
  "event_payload": {
    "equipment_id": "EQP-02",
    "lot_id": "LOT-001",
    "step": "STEP_007",
    "recipe_id": "RCP_5_NM",
    "spc_status": "OOC"
  }
}
```

## 5. deep_diagnostic 欄位 schema
```json
{
  "steps": [
    {
      "step_id": "s1_19e127dab35",
      "title": "XBar Pareto by step",      // skill.steps[].name (或 fallback step_id)
      "status": "pass" | "fail" | "error",
      "note": "8 stations OOC >= 1",
      "value": 8.0, "operator": ">=", "threshold": 1,
      "data_views": [
        {
          "block": "XBar OOC count by step",
          "columns": ["step","ooc_count"],
          "rows": [...],
          "total": 8
        }
      ],
      "charts": [...]                       // 若 pipeline 內有 chart block
    },
    ...
  ]
}
```

## 6. execution_log.llm_readable_data 整合 shape
```json
{
  "summary": "Confirm 2/5 OOC >= 2; Step s_xbar_pareto found 3 stations",
  "condition_met": true,
  "result_summary": {"triggered": true, "summary": "..."},
  "trigger_reason": { ... },      // 上面 §4
  "deep_diagnostic": { ... },     // 上面 §5
  "_alarm_output_schema": [...]    // UI render hint (table + scalar)
}
```

## 7. 硬刪除清單 (no back-compat)

### Java (delete files)
- `domain/patrol/AutoPatrolEntity.java`
- `domain/patrol/AutoPatrolRepository.java`
- `domain/pipeline/PipelineAutoCheckTriggerEntity.java`
- `domain/pipeline/PipelineAutoCheckTriggerRepository.java`
- `domain/skill/RoutineCheckEntity.java`
- `domain/skill/RoutineCheckRepository.java`
- `api/skill/SkillMaterializeService.java`
- `api/pipeline/PipelineController` 內: `publishAutoCheck`,
  `upsertAutoCheckTriggers`, `listAutoCheckBindings` 等 routes
- `scheduler.SchedulerHttpClient.dispatchAlarm` method
- `scheduler.api.InternalSchedulerController` `/dispatch-alarm/{id}` route
- `scheduler.patrol.EventDispatchService.dispatchAlarm` method + all fan-out
- `scheduler.patrol.AutoCheckExecutor` (if exists)
- `api.alarm.AlarmEnrichmentService.computeAutoCheckRuns`, `safeFindRun`
  (pb_pipeline_runs lookup paths)
- `api.alarm.AlarmEnrichmentService.diagFindings` 老 path
- `api.alarm.AlarmDtos`: 移除 `autoCheckRuns`, `diagnosticDataViews`,
  `diagnosticCharts`, `diagnosticAlert` fields

### Java (modify)
- `domain/alarm/AlarmEntity.java`: `diagnosticLogId` 欄位 KEEP (column 留)
  但程式不再寫不再讀。下版 V50 可考慮 DROP COLUMN
- `pipeline_kind` enum: 標 'auto_check' / 'auto_patrol' 為 deprecated,
  PipelineController 拒絕新 publish 為這兩個 kind

### Frontend
- `aiops-app/src/components/alarms/AlarmDetailLegacy.tsx`: 刪 `auto_check_runs`,
  `diagnostic_data_views`, `diagnostic_charts`, `diagnostic_alert`,
  `diagnostic_results`, `trigger_data_views` 等 fields render
- 重寫成 2 個 section: 觸發原因 + 深度診斷 (各自 read 新 shape)
- (考慮把檔名 AlarmDetailLegacy.tsx 改 AlarmDetail.tsx)

### DB (Flyway)
- `V49__drop_legacy_unified_skill_cleanup.sql`:
  ```sql
  DROP TABLE auto_patrols CASCADE;
  DROP TABLE pipeline_auto_check_triggers CASCADE;
  DROP TABLE routine_checks CASCADE;
  -- (optional V50) ALTER TABLE alarms DROP COLUMN diagnostic_log_id;
  ```
- 老 alarm rows (id ≤ 1017): UI 顯示空深度診斷 (接受，user 確認不要 back-compat)

## 8. 程式 Phase 順序

### Phase 1 — SkillRunnerService 統一 emit (Backend Java)
1. `runWithSink`: 加 `triggerType` 判斷 → event 跳 gate, schedule 跑 gate (若有)
2. `emitAlarmIfTriggered`: 計算 `trigger_reason` (依 mode 不同 shape)
3. `buildLlmReadableData`: 新版 `{trigger_reason, deep_diagnostic, ...}`
4. **移除** v30.16 的 `scheduler.dispatchAlarm(a.getId())` call
5. 修對應 unit tests + 加 trigger_reason / deep_diagnostic / Mode A vs B 各 case

### Phase 2 — AlarmEnrichmentService 對應新 shape
6. `buildFields`: 從 `findings.trigger_reason / deep_diagnostic` 直出
7. 砍 `computeAutoCheckRuns`, `runsByAlarmId`, `safeFindRun`, `diagFindings` paths
8. `AlarmDtos`: 移除 `autoCheckRuns` 等舊 fields
9. 修 RepositorySmokeTest etc.

### Phase 3 — 砍 legacy 路徑 (Backend Java)
10. 刪 `SkillMaterializeService`
11. 改寫 `EventDispatchService`:
    - 移除 `dispatchAlarm`
    - `dispatchEvent`: 改 query `skill_documents WHERE trigger_config->>'type'='event'`
      (JSONB path query) → for each match call `SkillRunnerService.run(slug, mapped_payload)`
12. 刪 `AutoPatrolEntity / AutoPatrolRepository` (+ migration 注意 cascade)
13. 刪 `PipelineAutoCheckTriggerEntity / PipelineAutoCheckTriggerRepository`
14. 刪 `RoutineCheckEntity / RoutineCheckRepository`
15. `PipelineController`: 刪 publish-auto-check / upsert-auto-check-triggers / list-auto-check-bindings routes (4-5 個 endpoint)
16. `scheduler` 子模組: 刪 `/dispatch-alarm/{id}` route
17. `pipeline_kind` enum: 'auto_check' / 'auto_patrol' deprecated, 新 publish 擋下

### Phase 4 — Schedule path 自動 cron (Backend, java-scheduler)
18. 新增 cron job `SkillScheduleTickerService` (`@Scheduled(fixedDelay=60000)`):
    每分鐘掃 `skill_documents WHERE status='stable' AND trigger_config->>'type'='schedule'`
19. 對每個 skill 依 `schedule.mode` (hourly / daily / interval-N-min) 比對 `skill.stats.last_run_at`
20. 該跑的 → call `SkillRunnerService.run(slug, {})` (= schedule trigger, Mode A)
21. 更新 `skill.stats.last_run_at` (existing field), `skill.stats.runs_total`

### Phase 5 — Frontend Alarm Detail 重寫
22. 重寫 `AlarmDetailLegacy.tsx` → `AlarmDetail.tsx`:
    - Header: title, severity, equipment, lot, step, event_time
    - 「觸發原因」section: render `findings.trigger_reason` (兩 mode 不同模板)
    - 「深度診斷 (Checklist)」section: render `findings.deep_diagnostic.steps[]`，
      每個 step 一張 card 含 status / note / data table / charts
    - 老 ack / disposition 區塊保留
23. 刪所有老 fields render
24. 對應 e2e 測 (Playwright) 補上

### Phase 6 — Flyway DROP legacy tables
25. `V49__drop_legacy_unified_skill_cleanup.sql` (見 §7)
26. EC2 手動 `psql -f` (Flyway disabled in prod)

### Phase 7 — Docs + Memory
27. `docs/PROJECT_HANDOFF.md`: 加 v30.17 milestone 段落
28. `docs/agent_workflow.html` 更新
29. `docs/module_relationships.html` 更新 (skill 模型統一了)
30. memory: 新 `project_unified_skill_model.md` 記錄此次架構決定

## 9. Edge Cases & Risks

| 情境 | 處理 |
|---|---|
| Mode B event 想 sanity check | 第一 step 放 step_check 當 gate。fail → alarm summary 註明「first step gate fail」但仍 emit (event 是事實) |
| Mode B event 沒 equipment_id | `equipment_id="(any)"` (v30.13 已有) |
| Schedule cron 預設多久 | 走 `trigger_config.schedule.mode` (hourly/daily/N-min)，scheduler 已有 cron infra |
| 老 alarm 1-1017 深度診斷顯示空 | **接受**。要好看可寫遷移 script 把 old execution_log/diagnostic_log 重塑為新 shape，但 user 確認不要 back-compat |
| `pb_pipeline_runs` 表 | **保留** (skill steps 跑時還是會寫，作為 pipeline-run 紀錄)。只是 `source_alarm_id` 不再寫 |
| Mode A 沒過 gate 仍需 execution_log 紀錄 | 寫 status=success, condition_met=false, alarm 不寫。System Monitor / Skill detail 可看「上次巡檢 ok」 |
| Phase 6 DROP TABLE destructive | 接受 (user 說不用備份)。但建議仍先 `pg_dump --table=auto_patrols,...` 留個 backup file 在 EC2 `/tmp/`，不長期保留 |
| skill_documents 數量大 (掃描成本) | 目前只有 3 個 skills；Phase 4 cron 掃描 < 10ms。Index 待 > 100 個 skill 時加 |
| Mode A trigger.type='schedule' 但 trigger.schedule missing | scheduler skip + log warn |

## 10. Open Issues (待討論，排進 Phase 對應位置)

### OI-1 — macro plan 沒含 chart phase 即使 user 要 chart
**症狀**: prompt `"檢查機台EQP-01 最後一次OOC 時，是否有多張SPC 也OOC (>2)，並且顯示該SPC charts"`
v30 goal_plan 生出來的 phases 沒有 `expected=chart` 的 phase，只有 step_check / data_view。

**3 個候選方案 (待 user 決定)**:
- (a) `nodes/goal_plan.py` system prompt 加 hard rule:
  「user 提及 chart/趨勢/圖/visualize/show → plan 必含至少 1 個 expected=chart 的 phase」
  → 簡單，但 LLM 可能還是漏（per `feedback_flow_in_graph_not_prompt.md`）
- (b) goal_plan 後加 deterministic check:
  掃 instruction 含 chart 關鍵字 set，但 phases 沒 chart kind → 自動 inject 一個 chart phase
  → graph-level enforcement，per 慣用模式
- (c) 拋 user goal_plan_confirmed SSE 時順便加 hint:
  `{requires_chart: true}` 給 UI 提示「要 chart 嗎？edit 加一個」
  → 把判斷推給 user

**建議**: (b) — 跟 `intent_completeness` graph gate 同樣的 deterministic 強制。
Plus (a) prompt 改 cosmetic 不算數，做也行（雙保險）。

### OI-2 — chat `intent_classifier` 每次 JSON parse fail
**症狀**: 從 user 多次 chat trace 看到:
```
WARNING intent_classifier failed (Extra data: line 5 column 1 (char 52))
        — defaulting to clear_chart pass-through
```
影響: classifier 沒分到正確 bucket，但 fallback path (clear_chart pass-through) 仍能跑，**不會 break 用戶體驗**，純效能/精度損失。

**檢驗**: LLM 回了 valid JSON 但後面又跟了多餘的字，json.loads 在第 5 行炸了。可能是:
- prompt 沒明確要求「ONLY JSON, no prose」
- LLM model 行為改變
- 或 LLM 連回兩段 JSON

**建議**: 改 classifier 用 `json.JSONDecoder().raw_decode(raw)` 取第一個 valid JSON object，不管後面的文字。簡單 robust。1-line patch。

### OI-3 (剛 ship) — chat 卡在 macro plan 確認
**Root cause**: `goal_plan_confirm_gate_node` 無條件 `interrupt()`，沒看 `skip_confirm`。chat caller 設 `skip_confirm=True` 但 v30 gate 不認 → graph 停在那 → chat tool_execute 收到空 SSE → chat LLM 自編 reply → user 沒看到 build 進度。

**已修 (v30.17a)**: `goal_plan_confirm_gate_node` 看 `state.skip_confirm`，True → 自動 confirm + emit `goal_plan_confirmed` event + skip interrupt。
4 unit tests pass。Deploy 2026-05-17。

---

## 11. 確認事項

請回覆「開始開發」啟動 Phase 1-7 全做。

或如想再調整:
- step `title` 欄位來源 (用 step.name? step.label?) — 目前假設 `skill.steps[].name`
- Phase 4 cron tick interval 想要更頻繁 (每 30 秒?) 還是每分鐘 ok?
- Phase 5 frontend 想保留 `AlarmDetailLegacy.tsx` 檔名還是改 `AlarmDetail.tsx`?
