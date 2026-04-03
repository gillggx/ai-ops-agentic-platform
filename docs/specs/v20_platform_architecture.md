# AIOps Platform v2.0 — Architecture Specification

**Date:** 2026-03-29
**Status:** In Development (Phase 1 Complete, Phase 2-3 Pending)

---

## 1. Core Concepts & Boundaries

| Concept | Definition | Producer | Consumer |
|---|---|---|---|
| **Event** | Raw signal from equipment (OOC, downtime, recipe_change) via Kafka/Tibco | Equipment / Event Bus | Auto-Patrol |
| **Skill** | Diagnostic function: takes event_payload, returns SkillFindings | Senior PE (via AI builder) | Auto-Patrol / Manual |
| **SkillFindings** | Structured result: `condition_met` + `evidence` + `impacted_lots` | Skill Executor | Auto-Patrol / Dashboard |
| **Alarm** | Human-facing alert with severity + evidence, requires action | Auto-Patrol | Technician |

**Key rule:** `trigger_alarm()` is removed from Skills. Alarm creation is delegated entirely to Auto-Patrol, which reads `condition_met` from SkillFindings.

---

## 2. Execution Flow

```
Equipment → Event Bus (OOC / downtime / recipe_change)
                ↓
         Auto-Patrol
         ├── event-driven:   event arrives → find matching patrol → run Skill
         └── schedule-driven: cron fires → expand target_scope → run Skill per equipment
                ↓
         Skill.run(event_payload)
         → SkillFindings {
               condition_met: bool,
               evidence: { ...output_schema fields... },
               impacted_lots: List[str],
               schema_warnings: List[str]
           }
                ↓
         if condition_met:
             Auto-Patrol → create Alarm(severity, title, findings)
             → notify(channels, users)
                ↓
         Technician sees Alarm in Operations Center Dashboard
```

---

## 3. Skill v2.0 Definition

### 3.1 Data Model

```
SkillDefinition {
  id, name, description
  trigger_event_id    → FK to event_types (NULL = schedule-only)
  trigger_mode        → "schedule" | "event" | "both"
  steps_mapping       → JSON: [{step_id, nl_segment, python_code}]
  output_schema       → JSON: [{field, type, label, columns?, x?, y?, bands?}]  ← NEW
  visibility, is_active, created_by, created_at, updated_at
}
```

### 3.2 output_schema Field Types

| Type | Display | Notes |
|---|---|---|
| `bool` | ✅/❌ badge | Always include `condition_met: bool` |
| `int` / `float` | Number | Counts, measurements |
| `str` | Text | Status descriptions |
| `list[str]` | Chip list | `impacted_lots` |
| `table` | Data table | Requires `columns: [{key, label, type}]` |
| `chart` | SPC line chart | Requires `x`, `y`, `bands` (e.g. `["ucl","lcl"]`) |

### 3.3 _findings Contract (LLM-generated code must assign this)

```python
_findings = {
    "condition_met": True,           # required — Auto-Patrol reads this
    "evidence": {
        "checked_records": 12,       # real values from MCP calls
        "ooc_in_recent": 3,
        "recent_records": [          # table type — list of dicts
            {"lotID": "LOT-001", "value": 102.3, "ucl": 98.5, "is_ooc": True},
        ],
    },
    "impacted_lots": ["LOT-001"],    # lots involved if condition_met
}
```

### 3.4 Available MCPs in Skill Code

```python
# Single snapshot — current state of a lot at a specific step
result = await execute_mcp('get_process_context', {
    'targetID': lot_id, 'step': step, 'objectName': 'SPC'
})
# → {charts: {xbar_chart: {value, ucl, lcl}}, spc_status: 'PASS'|'OOC'}

# Recent process history of a tool (no step needed)
history = await execute_mcp('get_object_snapshot_history', {
    'targetID': equipment_id, 'objectName': 'SPC'
})
# → list: [{spc_status: 'PASS'|'OOC', charts: {xbar_chart: {value, ucl, lcl}}}, ...]

# Recent process history of a lot
history = await execute_mcp('get_object_snapshot_history', {
    'targetID': lot_id, 'objectName': 'SPC'
})
# → list: [{spc_status: 'PASS'|'OOC', charts: {xbar_chart: {value, ucl, lcl}}}, ...]
```

---

## 4. Auto-Patrol

### 4.1 Data Model

```
AutoPatrol {
  id, name, description
  skill_id          → FK to skill_definitions
  trigger_mode      → "event" | "schedule"
  event_type_id     → FK to event_types (for trigger_mode="event")
  cron_expr         → cron string (for trigger_mode="schedule")
  target_scope      → JSON: {
                        type: "all_equipment" | "equipment_list" | "event_driven",
                        equipment_ids: [...]
                      }
  alarm_severity    → "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  alarm_title       → string
  notify_config     → JSON: {channels: ["email","slack"], users: [...]}
  is_active, created_by, created_at, updated_at
}
```

### 4.2 Execution Logic

```python
findings = await skill_executor.execute(skill_id, event_payload)
if findings.condition_met:
    alarm = create_alarm(
        severity=patrol.alarm_severity,
        title=patrol.alarm_title,
        evidence=findings.evidence,
        impacted_lots=findings.impacted_lots,
    )
    notify(patrol.notify_config, alarm)
```

---

## 5. Frontend Navigation Architecture

### Workspace 1 — Operations Center (Technician / 值班 PE)
- `Process Dashboard` — Alarm list (Critical/Warning first) + anomalous equipment status. Click alarm → slide-in panel shows SkillFindings using output_schema renderer.
- `Root Cause View` — Topology visualization + impact scope. Read-only, no config buttons.

### Workspace 2 — Knowledge Studio (Senior PE / QA)
- `Diagnostic Rules` — Skill Builder v3.0 (intent-driven). Shows `output_schema` preview after AI generation. Try-run result rendered using declared schema (table/chart/bool).
- `Analysis Views` — Custom MCP Builder. Prompt → AI script → reusable data view.
- `Auto-Patrols` — Configure event-driven and schedule-driven patrols. Bind to Skill + set alarm config + notify targets.

### Workspace 3 — System Admin (IT — hidden by default)
- `Data Sources` — MCP API endpoint configuration (endpoint_url, auth, method).
- `Event Registry` — Register Kafka/Tibco event schemas (payload field definitions).
- `Settings` — Permissions, system parameters.

---

## 6. DB Migrations

| Migration | Changes |
|---|---|
| `20260329_0001` | `skill_definitions.output_schema TEXT` + `auto_patrols` table |

---

## 7. Implementation Phases

| Phase | Scope | Status |
|---|---|---|
| **Phase 1** | Skill v2.0 backend (schemas, executor, prompts, migration) | ✅ Complete |
| **Phase 2** | Frontend 3-Workspace restructure + output_schema renderer | 🔄 In Progress |
| **Phase 3** | Auto-Patrol backend + frontend | ⏳ Pending |
