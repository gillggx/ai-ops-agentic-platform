# v12 QA Acceptance Report

**Date**: 2026-03-07
**Branch**: main
**Server**: http://localhost:8765
**Auth**: admin / admin (JWT Bearer)

---

## Summary

| # | Test Case | Result |
|---|-----------|--------|
| TC1 | System MCP Default Wrapper | **PASS** |
| TC2 | UI List Isolation (`?type=` filter) | **PASS** |
| TC3 | Draft E2E Handover | **PASS** |
| TC4 | XML Safety / Markdown Compiler | **PASS** |
| TC5 | Bi-directional Parser | **PASS** |

All 5 mandatory QA test cases **PASSED**.

---

## TC1 — System MCP Default Wrapper

**Spec**: `POST /api/v1/execute/mcp/{mcp_id}` on a `mcp_type='system'` MCP must:
- Return `data.output_data.ui_render.type = 'data_grid'`
- Return `dataset` containing the raw API data
- Return `_raw_dataset` preserving original response

**Command**:
```bash
curl -X POST http://localhost:8765/api/v1/execute/mcp/6 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"lot_id":"L2603001","operation_number":"3200"}'
```

**Response** (truncated):
```json
{
    "status": "success",
    "mcp_id": 6,
    "output_data": {
        "output_schema": {},
        "dataset": [
            {
                "lot_id": "L2603001",
                "operation_number": "3200",
                "apc_name": "TETCH03_RCD_Control",
                "apc_model_name": "RCD_EWMA_v1.5",
                "parameters": [
                    {"name": "CHF3_Gas_Offset", "value": 2.8},
                    {"name": "RF_Power_Delta", "value": -9}
                ]
            }
        ],
        "ui_render": {
            "type": "data_grid",
            "charts": [],
            "chart_data": null
        },
        "_raw_dataset": [...same as dataset...],
        "_is_processed": false
    }
}
```

**Assertions**:
- `output_data.ui_render.type` = `"data_grid"` ✓
- `output_data.dataset` is non-empty list with APC data ✓
- `output_data._raw_dataset` = `output_data.dataset` (raw passthrough) ✓

**New endpoint added**: `app/routers/agent_execute_router.py` — `POST /execute/mcp/{mcp_id}`

---

## TC2 — UI List Isolation

**Spec**: `GET /mcp-definitions?type=custom` must return only custom MCPs; no filter returns all.

**Commands**:
```bash
# Custom only
curl "http://localhost:8765/api/v1/mcp-definitions?type=custom" \
  -H "Authorization: Bearer $TOKEN"

# All types
curl "http://localhost:8765/api/v1/mcp-definitions" \
  -H "Authorization: Bearer $TOKEN"
```

**Results**:
- `?type=custom`: Count=5, breakdown={'custom': 5}, system_in_list=False ✓
- No filter: Total=10, breakdown={'custom': 5, 'system': 5} ✓

**Assertions**:
- `?type=custom` returns exactly 5 custom MCPs, zero system MCPs ✓
- No filter returns all 10 MCPs (5 system + 5 custom) ✓
- System MCP IDs 6–10 were migrated from DataSubjects via `20260307_0003_add_system_mcp` migration ✓

---

## TC3 — Draft E2E Handover

**Spec**: `POST /agent/draft/skill` must:
- Write to Draft DB (not `skill_definitions`)
- Return `draft_id` (UUID), `draft_type`, `status=pending`, `deep_link_data`
- `GET /agent/draft/{draft_id}` must return the same draft

**Commands**:
```bash
# Create draft
curl -X POST http://localhost:8765/api/v1/agent/draft/skill \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"TC3 Draft","description":"QA test","diagnostic_prompt":"if abnormal>3 then ABNORMAL","mcp_ids":[1]}'

# Verify NOT in skill registry
curl "http://localhost:8765/api/v1/skill-definitions" -H "Authorization: Bearer $TOKEN"

# GET draft
curl "http://localhost:8765/api/v1/agent/draft/{draft_id}" -H "Authorization: Bearer $TOKEN"
```

**Results**:
```json
{
  "draft_id": "f9195562-9b90-45c7-b790-b22ad865479b",
  "draft_type": "skill",
  "status": "pending",
  "deep_link_data": {
    "view": "skill-builder",
    "draft_id": "f9195562-9b90-45c7-b790-b22ad865479b",
    "auto_fill": {
      "name": "TC3 Draft",
      "description": "QA test",
      "diagnostic_prompt": "if abnormal>3 then ABNORMAL"
    }
  }
}
```

**Assertions**:
- `draft_id` is a UUID ✓
- `draft_type` = `"skill"` ✓
- `status` = `"pending"` ✓
- "TC3 Draft" NOT in `skill-definitions` registry (6 existing skills, none named "TC3 Draft") ✓
- `GET /agent/draft/{draft_id}` returns same UUID/type/status ✓

---

## TC4 — XML Safety / Markdown Compiler

**Spec**: A `diagnostic_prompt` containing YAML-breaking chars (`---`, `# fake header`) must be safely
wrapped inside `<condition>...</condition>` in the tools manifest. The YAML header must not be polluted.

**Setup** (PATCH skill 1):
```bash
curl -X PATCH http://localhost:8765/api/v1/skill-definitions/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "diagnostic_prompt": "如果 abnormal_count > 3 則 ABNORMAL\n---\n# fake header injection\n正常情況 NORMAL",
    "visibility": "public"
  }'
```

**Verification** (`GET /agent/tools_manifest`):
```
Extracted <condition> content:
  '如果 abnormal_count > 3 則 ABNORMAL\n---\n# fake header injection\n正常情況 NORMAL'

YAML header block (first section):
  '---\nname: APC abormal change detection\ndescription: 本技能是一套完整的自動化診斷管線。...\n---'
```

**Assertions**:
- `---` appears inside `<condition>` tag, not as YAML separator ✓
- `# fake header injection` appears inside `<condition>` tag ✓
- YAML front matter (`---...---`) is clean — only `name:` and `description:` keys ✓
- The Markdown document structure (YAML + sections + `<rules>` block) is valid ✓

---

## TC5 — Bi-directional Parser

**Spec**: `PUT /agentic/skills/{skill_id}/raw` with modified `<expert_action>` block must update
`human_recommendation` in the DB.

**State before**:
```
human_recommendation: '執行調機、pi-run 的流程確認'
```

**Command**:
```bash
curl -X PUT http://localhost:8765/api/v1/agentic/skills/1/raw \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "raw_markdown": "---\nname: ...\n---\n...\n<rules>\n  <condition>...</condition>\n  <target_extraction>machine_id</target_extraction>\n  <expert_action>\n    ⚠️ 若狀態為 ABNORMAL...\n    Action: TC5_UPDATED_ACTION — 立即通知 IT Sponsor 並開立異常工單\n  </expert_action>\n</rules>"
  }'
```

**Response**:
```json
{
  "updated_fields": ["name", "description", "diagnostic_prompt", "problem_subject", "human_recommendation"]
}
```

**State after** (GET skill 1):
```
human_recommendation: 'TC5_UPDATED_ACTION — 立即通知 IT Sponsor 並開立異常工單'
```

**Assertions**:
- `human_recommendation` updated from old value to new value ✓
- `updated_fields` includes `"human_recommendation"` ✓
- Other fields (`name`, `description`, `diagnostic_prompt`, `problem_subject`) also parsed ✓

---

## Infrastructure Changes Completed

### New Files
| File | Description |
|------|-------------|
| `alembic/versions/20260307_0001_add_visibility.py` | Adds `visibility` column to skill/mcp tables |
| `alembic/versions/20260307_0002_add_agent_drafts.py` | Creates `agent_drafts` table |
| `alembic/versions/20260307_0003_add_system_mcp.py` | Adds 4 system MCP columns; migrates DataSubjects |
| `app/models/agent_draft.py` | AgentDraftModel ORM |
| `app/routers/agent_draft_router.py` | Draft CRUD + publish endpoints |
| `app/routers/agent_execute_router.py` | `/execute/skill/{id}` + `/execute/mcp/{id}` |
| `app/routers/agent_router.py` | `/agent/tools_manifest` + meta_tools |
| `app/routers/agentic_skill_router.py` | Bi-directional OpenClaw Markdown read/write |
| `app/services/skill_execute_service.py` | SkillExecuteService with strict view separation |

### Modified Files
| File | Key Changes |
|------|-------------|
| `app/models/mcp_definition.py` | Added `mcp_type`, `api_config`, `input_schema`, `system_mcp_id` |
| `app/schemas/mcp_definition.py` | `system_mcp_id` field, `api_config`/`input_schema` as dict |
| `app/services/mcp_definition_service.py` | Default Wrapper for system MCPs; `ui_render.type='data_grid'` |
| `app/services/copilot_service.py` | system_mcp_id fallback; DS lookup deprecated |
| `main.py` | All new routers registered |
| `static/builder.js` | DS→System MCP rename; `?type=custom/system` filters; System MCP drawer |
| `static/index.html` | nav-system-mcps; view-system-mcps; Raw mode toggle for Skill Editor |

### Database (dev.db)
- Schema rebuilt to make `data_subject_id` nullable (SQLite limitation)
- 5 DataSubjects migrated as system MCPs (IDs 6–10, `mcp_type='system'`)
- All 5 custom MCPs have `system_mcp_id` set (non-null)

---

## v12 Architecture: "萬物皆 MCP"

```
IT Sponsor → System MCP (mcp_type='system')
                api_config: {endpoint_url, method, headers}
                input_schema: {fields: [...]}
                └─ Default Wrapper: fetches raw API → wraps as Standard Payload
                   ui_render.type = 'data_grid'

User → Custom MCP (mcp_type='custom')
                system_mcp_id → points to System MCP
                processing_script: Python → transforms raw data
                └─ run_with_data: fetch via system MCP → run script → Standard Payload

Agent → Skill (mcp_ids → [custom MCP id])
                diagnostic_prompt, problem_subject, human_recommendation
                OpenClaw Markdown: GET/PUT /agentic/skills/{id}/raw
                Execute: POST /execute/skill/{id} → llm_readable_data + ui_render_payload

Agent Proposals → Draft (draft_type='skill'|'mcp')
                Status: pending → approved → published
                POST /agent/draft/{type} → Draft DB only (never real registry)
                POST /agent/draft/{id}/publish → writes to real registry
```
