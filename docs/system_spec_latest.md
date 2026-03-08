# Glass Box AI Diagnostic Platform — System Specification (Latest)

**Version**: v13.5
**Last Updated**: 2026-03-08
**Status**: Active Development — Phases 1–15 Complete

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| v13.5 | 2026-03-08 | Split-screen Dashboard; Agent pre-flight validation; production httpx loopback fix; session history boundary sanitization; MCP real-name in tabs; System MCP execution fixes |
| v13.0 | 2026-03-07 | UI Phase 15: 診斷站 as default landing page; Skill Builder & MCP Builder full-page L/R editors (two-state list+editor); 排程巡檢管理 removed from sidebar; Agent Console in diagnose page; Plotly chart horizontal legend forced below plot. Code gen `max_tokens` 2048→4096 + `compile()` pre-check in `mcp_builder_service.py`. |
| v12.0 | 2026-03-04 | Skill card redesign: chart/data tabs, problem_object, suggestion action. `_auto_chart` fallback. Diagnosis prompt returns `problem_object`. |
| v11.0 | 2026-03-04 | Initial living spec created; covers all phases 1–11. Hard-coded config extracted to `config.py`. Code style refactored (type hints + docstrings). |

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Application Entry Point](#3-application-entry-point)
4. [API Endpoints](#4-api-endpoints)
5. [Database Schema](#5-database-schema)
6. [Configuration](#6-configuration)
7. [Skills & Tools](#7-skills--tools)
8. [Frontend Assets](#8-frontend-assets)
9. [Dependencies](#9-dependencies)
10. [Database Migrations](#10-database-migrations)
11. [Response Formats](#11-response-formats)
12. [Running the Service](#12-running-the-service)
14. [Agent v13 架構](#14-agent-v13-架構)

---

## 1. System Overview

**Project Root**: `fastapi_backend_service/`
**Application Name**: Glass Box AI Diagnostic Platform
**Version**: 1.0.0 (app), v13.5 (spec)

### Purpose

AI-powered semiconductor process diagnostic engine. Provides:
- Agentic LLM diagnosis driven by structured Skill definitions
- MCP (Measurement Collection Pipeline) builder for data-to-insight pipeline authoring
- Intent-driven Copilot UI with slash commands and slot filling
- Event-triggered and scheduled routine inspection workflows
- Help chat assistant for system usage Q&A

### Core Domain

Semiconductor etch process quality control (SPC OOC detection, APC compensation, recipe integrity, equipment health).

---

## 2. Architecture

### Layers

```
Static SPA (index.html + app.js + builder.js)
  ↓
API Routers  (/api/v1/*)
  ↓
Services     (business logic, LLM calls)
  ↓
Repositories (data access)
  ↓
SQLAlchemy 2.0 ORM Models
  ↓
SQLite (dev) / PostgreSQL (prod)
```

### Key Patterns

| Pattern | Implementation |
|---------|---------------|
| Dependency Injection | FastAPI `Depends()` wired in `app/dependencies.py` |
| JWT Authentication | `python-jose` + `bcrypt` |
| Async DB | SQLAlchemy 2.0 `AsyncSession` (`aiosqlite` / `asyncpg`) |
| SSE Streaming | Fetch API + ReadableStream (NOT EventSource — lacks auth header support) |
| LLM | Anthropic Claude via `anthropic>=0.40.0` |
| Scheduler | APScheduler `AsyncIOScheduler` |
| Config | `pydantic-settings` `BaseSettings`, `.env` file |

---

## 3. Application Entry Point

**File**: `main.py`

### Lifespan

- **Startup**: DB init → seed default data (users, DataSubjects, EventTypes, SystemParameters) → start APScheduler
- **Shutdown**: stop APScheduler, flush logging

### Middleware

1. `CORSMiddleware` — origins from `config.ALLOWED_ORIGINS`
2. `RequestLoggingMiddleware` — structured logging + `X-Request-ID` header

### Global Exception Handlers

| Exception | HTTP Code |
|-----------|-----------|
| `AppException` | As specified (e.g. 404, 409) |
| `RequestValidationError` | 422 with field errors |
| `StarletteHTTPException` | As specified |
| `Exception` (catch-all) | 500 |

### Health Endpoint

`GET /health` → `HealthResponse {status, version, database, timestamp}`

### Static Files

Mounted at `/` after all API routes — `StaticFiles(directory="./static", html=True)`.

---

## 4. API Endpoints

All routes use prefix `/api/v1` (configurable via `API_V1_PREFIX`).

### 4.1 Authentication (`/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/login` | None | Authenticate and return JWT |
| GET | `/auth/me` | Bearer JWT | Get current user profile |

### 4.2 Users (`/users`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/users/` | Bearer JWT | List users (skip, limit 1–100) |
| POST | `/users/` | None | Create user (HTTP 201) |
| GET | `/users/{user_id}` | Bearer JWT | Get user by ID |
| PUT | `/users/{user_id}` | Bearer JWT | Update user (owner or superuser) |
| DELETE | `/users/{user_id}` | Bearer JWT | Delete user (owner or superuser) |

### 4.3 Items (`/items`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/items/` | Bearer JWT | List all items (paginated) |
| GET | `/items/me` | Bearer JWT | List current user's items |
| POST | `/items/` | Bearer JWT | Create item (HTTP 201) |
| GET | `/items/{item_id}` | Bearer JWT | Get item by ID |
| PUT | `/items/{item_id}` | Bearer JWT | Update item (owner or superuser) |
| DELETE | `/items/{item_id}` | Bearer JWT | Delete item (owner or superuser) |

### 4.4 Diagnostic (`/diagnose`)

| Method | Path | Response | Auth | Description |
|--------|------|----------|------|-------------|
| POST | `/diagnose/` | SSE | Bearer JWT | AI agent (free-text issue description) |
| POST | `/diagnose/event-driven` | JSON | Bearer JWT | Full event-driven pipeline |
| POST | `/diagnose/event-driven-stream` | SSE | Bearer JWT | Event-driven pipeline (progressive cards) |
| POST | `/diagnose/copilot-chat` | SSE | Bearer JWT | Intent-driven copilot with slot filling |

**Request Bodies**:
- `DiagnoseRequest`: `{issue_description: str}`
- `EventDrivenDiagnoseRequest`: `{event_type: str, event_id: int, params: {...}}`
- `CopilotChatRequest`: `{message: str, slot_context: {...}, history: [...]}`

### 4.5 Builder (`/builder`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/builder/auto-map` | Bearer JWT | Semantic Event→MCP param mapping |
| POST | `/builder/validate-logic` | Bearer JWT | Validate diagnostic prompt field references |
| POST | `/builder/suggest-logic` | Bearer JWT | Generate PE-grade logic suggestions (3–5) |

### 4.6 Data Subjects (`/data-subjects`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/data-subjects/` | Bearer JWT |
| GET | `/data-subjects/{ds_id}` | Bearer JWT |
| POST | `/data-subjects/` | Bearer JWT |
| PATCH | `/data-subjects/{ds_id}` | Bearer JWT |
| DELETE | `/data-subjects/{ds_id}` | Bearer JWT |

### 4.7 Event Types (`/event-types`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/event-types/` | Bearer JWT |
| GET | `/event-types/{et_id}` | Bearer JWT |
| POST | `/event-types/` | Bearer JWT |
| PATCH | `/event-types/{et_id}` | Bearer JWT |
| DELETE | `/event-types/{et_id}` | Bearer JWT |

### 4.8 MCP Definitions (`/mcp-definitions`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/mcp-definitions/` | Bearer JWT | List MCPs |
| GET | `/mcp-definitions/{mcp_id}` | Bearer JWT | Get MCP |
| POST | `/mcp-definitions/` | Bearer JWT | Create MCP |
| PATCH | `/mcp-definitions/{mcp_id}` | Bearer JWT | Update MCP |
| DELETE | `/mcp-definitions/{mcp_id}` | Bearer JWT | Delete MCP |
| POST | `/mcp-definitions/{mcp_id}/generate` | Bearer JWT | LLM-generate script + schema + UI config |
| POST | `/mcp-definitions/check-intent` | Bearer JWT | Validate processing intent clarity |
| POST | `/mcp-definitions/try-run` | Bearer JWT | Generate + sandbox execute |
| POST | `/mcp-definitions/{mcp_id}/run-with-data` | Bearer JWT | Execute stored script with raw_data |

**Query Param**: `POST /mcp-definitions/?type=system|custom` — 列表過濾支援
- `GET /mcp-definitions/?type=system` — 回傳 System MCP 列表
- `GET /mcp-definitions/?type=custom` — 回傳 Custom MCP 列表

### 4.9 Skill Definitions (`/skill-definitions`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/skill-definitions/` | Bearer JWT | List Skills |
| GET | `/skill-definitions/{skill_id}` | Bearer JWT | Get Skill |
| POST | `/skill-definitions/` | Bearer JWT | Create Skill |
| PATCH | `/skill-definitions/{skill_id}` | Bearer JWT | Update Skill |
| DELETE | `/skill-definitions/{skill_id}` | Bearer JWT | Delete Skill |
| GET | `/skill-definitions/{skill_id}/mcp-output-schemas` | Bearer JWT | Output schemas of all bound MCPs |
| POST | `/skill-definitions/auto-map` | Bearer JWT | DS field → Event attr mapping |
| POST | `/skill-definitions/check-diagnosis-intent` | Bearer JWT | Validate diagnostic prompt |
| POST | `/skill-definitions/try-diagnosis` | Bearer JWT | Simulate diagnosis (LLM) |
| POST | `/skill-definitions/check-code-diagnosis-intent` | Bearer JWT | Code diagnosis readiness check |
| POST | `/skill-definitions/generate-code-diagnosis` | Bearer JWT | Generate Python diagnostic code |

### 4.10 System Parameters (`/system-parameters`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/system-parameters/` | Bearer JWT | List all parameters |
| PATCH | `/system-parameters/{key}` | Bearer JWT | Update parameter value |

### 4.11 Routine Checks (`/routine-checks`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/routine-checks/` | Bearer JWT | List all periodic jobs |
| POST | `/routine-checks/` | Bearer JWT | Create (HTTP 201); auto-creates EventType if needed |
| GET | `/routine-checks/{check_id}` | Bearer JWT | Get check |
| PUT | `/routine-checks/{check_id}` | Bearer JWT | Update (reschedules if interval changed) |
| DELETE | `/routine-checks/{check_id}` | Bearer JWT | Delete (unschedules job) |
| POST | `/routine-checks/{check_id}/run-now` | Bearer JWT | Manual trigger outside schedule |

### 4.12 Generated Events (`/generated-events`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/generated-events/` | Bearer JWT | List alarms (limit 200) |
| GET | `/generated-events/{event_id}` | Bearer JWT | Get alarm |
| PATCH | `/generated-events/{event_id}/status` | Bearer JWT | Update status (pending/acknowledged/resolved) |
| DELETE | `/generated-events/{event_id}` | Bearer JWT | Delete alarm |

### 4.13 Help Chat (`/help`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/help/chat` | Bearer JWT | SSE usage Q&A (product spec + user manual context) |

### 4.14 Agent (`/agent`, `/execute`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/agent/chat/stream` | Bearer JWT | Agentic loop SSE stream |
| GET | `/agent/tools_manifest` | Bearer JWT | Tool schemas + meta_tools |
| GET | `/agent/brain` | Bearer JWT | User soul + preferences |
| PATCH | `/agent/brain` | Bearer JWT | Update soul/preferences |
| POST | `/agent/draft/skill` | Bearer JWT | Create skill draft (agent-only) |
| POST | `/agent/draft/mcp` | Bearer JWT | Create MCP draft (agent-only) |
| GET | `/agent/drafts` | Bearer JWT | List pending drafts |
| POST | `/execute/mcp/{mcp_id}` | Bearer JWT | Execute MCP (system+custom); returns mcp_name, row_count, output_data, llm_readable_data |
| POST | `/execute/skill/{skill_id}` | Bearer JWT | Execute Skill; returns llm_readable_data, ui_render_payload |

### 4.15 Mock Data (`/mock`)

No authentication required.

| Method | Path | Query Params | Description |
|--------|------|--------------|-------------|
| GET | `/mock/apc` | `lot_id` (req), `operation_number` (default: 3200) | APC mock data |
| GET | `/mock/recipe` | `lot_id`, `tool_id`, `operation_number` (all req) | Recipe params |
| GET | `/mock/ec` | `tool_id` (req) | Equipment Constants |
| GET | `/mock/spc` | `chart_name`, `lot_id`, `tool_id` (optional) | 100 SPC records |
| GET | `/mock/apc_tuning` | `apc_name` (optional) | APC etchTime data |

---

## 5. Database Schema

### 5.1 `users`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK, Auto-increment |
| `username` | String(150) | UNIQUE, Index |
| `email` | String(255) | UNIQUE, Index |
| `hashed_password` | String(255) | NOT NULL |
| `is_active` | Boolean | Default: True |
| `is_superuser` | Boolean | Default: False |
| `roles` | Text | Default: '[]' — JSON: ["it_admin", "expert_pe", "general_user"] |
| `created_at` | DateTime(tz) | Server default: now() |
| `updated_at` | DateTime(tz) | Server default + On update |

### 5.2 `items`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK, Auto-increment |
| `title` | String(255) | NOT NULL, Index |
| `description` | Text | Nullable |
| `is_active` | Boolean | Default: True |
| `owner_id` | Integer | FK→users.id, Cascade delete |
| `created_at` | DateTime(tz) | Server default |
| `updated_at` | DateTime(tz) | Server default + On update |

### 5.3 `data_subjects`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK |
| `name` | String(200) | UNIQUE, Index |
| `description` | Text | NOT NULL |
| `api_config` | Text | NOT NULL — JSON: `{endpoint_url, method, headers}` |
| `input_schema` | Text | NOT NULL — JSON: `{fields: [{name, type, description, required}]}` |
| `output_schema` | Text | NOT NULL — JSON: `{fields: [{name, type, description}]}` |
| `is_builtin` | Boolean | Default: False |
| `created_at` / `updated_at` | DateTime(tz) | Standard |

**Built-in DataSubjects** (seeded on startup):

| Name | Endpoint |
|------|----------|
| APC_Data | `/api/v1/mock/apc` |
| Recipe_Data | `/api/v1/mock/recipe` |
| EC_Data | `/api/v1/mock/ec` |
| SPC_Chart_Data | `/api/v1/mock/spc` |
| APC_tuning_value | `/api/v1/mock/apc_tuning` |

### 5.4 `event_types`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | Integer | PK |
| `name` | String(200) | UNIQUE, Index |
| `description` | Text | NOT NULL |
| `attributes` | Text | NOT NULL — JSON: `[{name, type, description, required}]` |
| `diagnosis_skill_ids` | Text | NOT NULL — JSON: `[int]` or `[{skill_id, param_mappings}]` |
| `created_at` / `updated_at` | DateTime(tz) | Standard |

**Built-in EventType** (seeded on startup):

`SPC_OOC_Etch_CD` — Etch CD SPC out-of-control event.
Key attributes: `lot_id`, `tool_id`, `chamber_id`, `recipe_id`, `operation_number`, `apc_model_name`, `ooc_parameter`, `rule_violated`, `consecutive_ooc_count`, `SPC_CHART`.

### 5.5 `mcp_definitions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `name` | String(200) | UNIQUE |
| `description` | Text | NOT NULL |
| `data_subject_id` | Integer | FK→data_subjects.id |
| `processing_intent` | Text | User-written intent description |
| `processing_script` | Text | Nullable — LLM-generated Python |
| `output_schema` | Text | Nullable — JSON output structure |
| `ui_render_config` | Text | Nullable — Plotly chart config |
| `input_definition` | Text | Nullable — input params spec |
| `sample_output` | Text | Nullable — actual Try Run output |
| `created_at` / `updated_at` | DateTime(tz) | Standard |
| `mcp_type`     | String(10) | Default 'custom'; 'system' = IT-managed data source |
| `api_config`   | Text | System MCP only — JSON: {endpoint_url, method, headers} |
| `input_schema` | Text | System MCP only — JSON: {fields: [{name, type, description, required}]} |
| `system_mcp_id`| Integer | FK→mcp_definitions.id; custom MCP's parent system MCP |
| `visibility`   | String(20) | 'public' \| 'private' (default 'private') |

### 5.6 `skill_definitions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `name` | String(200) | UNIQUE |
| `description` | Text | NOT NULL |
| `event_type_id` | Integer | FK→event_types.id, Nullable |
| `mcp_ids` | Text | JSON: `[int]` — bound MCPs |
| `param_mappings` | Text | Nullable — JSON: `[{event_field, mcp_id, mcp_param, confidence}]` |
| `problem_subject` | String(300) | Nullable — monitored entity description |
| `diagnostic_prompt` | Text | Nullable — condition check prompt |
| `human_recommendation` | Text | Nullable — expert action (NOT LLM-generated) |
| `last_diagnosis_result` | Text | Nullable — JSON: last output + metadata |
| `created_at` / `updated_at` | DateTime(tz) | Standard |

### 5.7 `system_parameters`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `key` | String(100) | UNIQUE |
| `value` | Text | Nullable |
| `description` | String(500) | Nullable |
| `updated_at` | DateTime(tz) | On update |

**Built-in Keys**: `PROMPT_MCP_GENERATE`, `PROMPT_MCP_TRY_RUN`, `PROMPT_SKILL_DIAGNOSIS`.

### 5.8 `generated_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `event_type_id` | Integer | FK→event_types.id |
| `source_skill_id` | Integer | FK→skill_definitions.id |
| `source_routine_check_id` | Integer | FK→routine_checks.id, Nullable |
| `mapped_parameters` | Text | JSON: parameter values |
| `skill_conclusion` | Text | Nullable — summary |
| `status` | String(20) | Default: 'pending' (pending/acknowledged/resolved) |
| `created_at` / `updated_at` | DateTime(tz) | Standard |

### 5.9 `routine_checks`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer | PK |
| `name` | String(200) | NOT NULL |
| `skill_id` | Integer | FK→skill_definitions.id |
| `skill_input` | Text | JSON: preset parameter values |
| `trigger_event_id` | Integer | FK→event_types.id, Nullable — fires on ABNORMAL result |
| `event_param_mappings` | Text | Nullable — pre-configured field mappings |
| `schedule_interval` | String(20) | Default: '1h' (30m/1h/4h/8h/12h/daily) |
| `is_active` | Boolean | Default: True |
| `last_run_at` | Text | Nullable — ISO timestamp |
| `last_run_status` | String(20) | Nullable — NORMAL/ABNORMAL/ERROR |
| `created_at` / `updated_at` | DateTime(tz) | Standard |

### 5.11 `agent_sessions`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| session_id | String | UNIQUE |
| user_id | Integer | FK→users.id |
| messages | Text | JSON: conversation history (last 20 messages) |
| expires_at | DateTime | 24h TTL |
| created_at | DateTime | Standard |

### 5.12 `agent_memories`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | FK→users.id |
| content | Text | 純文字記憶 |
| embedding | BLOB | JSON array (SQLite) / pgvector (prod) |
| source | String(50) | 'diagnosis' \| 'user_preference' \| 'manual' |
| ref_id | String(100) | Nullable — related skill_id or mcp_id |
| created_at / updated_at | DateTime | Standard |

### 5.13 `agent_drafts`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| draft_id | String | UNIQUE (UUID) |
| user_id | Integer | FK→users.id |
| draft_type | String(20) | 'skill' \| 'mcp' |
| payload | Text | JSON: proposed record content |
| status | String(20) | 'pending' \| 'published' \| 'rejected' |
| created_at / updated_at | DateTime | Standard |

### 5.14 `user_preferences`

| Column | Type | Notes |
|--------|------|-------|
| id | Integer | PK |
| user_id | Integer | UNIQUE FK→users.id |
| preferences | Text | Free-form text |
| soul_override | Text | Admin override for soul prompt |
| created_at / updated_at | DateTime | Standard |

---

## 6. Configuration

**File**: `app/config.py` — `pydantic-settings` `BaseSettings`, reads from `.env` (UTF-8, case-sensitive).

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `APP_NAME` | str | "FastAPI Backend Service" | App display name |
| `APP_VERSION` | str | "1.0.0" | Version |
| `DEBUG` | bool | False | Debug mode |
| `DATABASE_URL` | str | `sqlite+aiosqlite:///./dev.db` | DB connection string |
| `SECRET_KEY` | str | (insecure default) | **Change in production** — JWT signing key |
| `ALGORITHM` | str | "HS256" | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | int | 720 | JWT expiry (12 hours) |
| `ALLOWED_ORIGINS` | str | "*" | CORS origins (comma-separated) |
| `LOG_LEVEL` | str | "INFO" | DEBUG/INFO/WARNING/ERROR/CRITICAL |
| `API_V1_PREFIX` | str | "/api/v1" | URL prefix |
| `ANTHROPIC_API_KEY` | str | "" | Claude API key |
| `LLM_MODEL` | str | "claude-opus-4-6" | Anthropic model ID for all LLM calls |
| `LLM_MAX_TOKENS_DIAGNOSTIC` | int | 4096 | Max tokens for diagnostic agent loop |
| `LLM_MAX_TOKENS_GENERATE` | int | 4096 | Max tokens for MCP/Skill generation |
| `LLM_MAX_TOKENS_CHAT` | int | 2048 | Max tokens for help chat & copilot |
| `HTTPX_TIMEOUT_SECONDS` | float | 15.0 | HTTP client timeout for DataSubject calls |
| `SCHEDULER_MISFIRE_GRACE_TIME_SECONDS` | int | 300 | APScheduler grace period |

`get_settings()` is cached with `@lru_cache(maxsize=1)`.

---

## 7. Skills & Tools

> **Two kinds of "Skills" exist in this system. Section 7.0 describes DB-driven Skills (the primary workflow). Sections 7.1–7.5 describe the legacy hard-coded agent skills.**

### 7.0 DB-Driven Skill Execution Flow

A **Skill** is a DB record (`skill_definitions` table) created via the Skill Builder UI. When it is triggered, the following pipeline runs:

```
POST /api/v1/diagnose/event-driven-stream
  { event_type_id, parameters }
        │
        ▼
EventPipelineService.stream()
  1. Look up all Skills registered for this EventType
  2. For each Skill (in order):
        │
        ▼
  _run_skill(skill, params, base_url)
        │
        ├─ A. Resolve MCP
        │      skill.mcp_id → SkillDefinition → MCPDefinition
        │
        ├─ B. Fetch DataSubject data
        │      mcp.data_subject_id → DataSubject.api_config.endpoint_url
        │      GET {endpoint_url}?{param_mappings resolved from event params}
        │      Returns raw JSON (list of records)
        │
        ├─ C. Run MCP processing script (Sandbox)
        │      execute_script(mcp.processing_script, raw_data)
        │      Returns Standard Payload or raw data
        │
        ├─ D. Normalize output → Standard Payload
        │      _normalize_output(output_data, mcp.output_schema)
        │      → {output_schema, dataset, ui_render: {type, chart_data}}
        │
        ├─ E. Auto-generate chart (if chart_data=null)
        │      _auto_chart(dataset, mcp.ui_render_config)
        │      Uses Plotly go.Scatter with x_axis/y_axis/series from ui_render_config
        │
        ├─ F. Diagnosis (Python-code path, preferred)
        │      If skill.last_diagnosis_result.generated_code exists:
        │        execute_diagnose_fn(generated_code, {mcp_name: output_data})
        │        → Python sandbox returns: {status, diagnosis_message, problem_object}
        │        Then: summarize_diagnosis(python_result, diagnostic_prompt, mcp_outputs)
        │        → LLM returns: {summary}
        │
        ├─ F'. Diagnosis fallback (pure LLM, when no generated_code)
        │      try_diagnosis(skill.diagnostic_prompt, mcp_output=output_data)
        │      Returns: {status, conclusion, evidence, summary, problem_object}
        │
        └─ G. Return SkillPipelineResult
               {status, conclusion, evidence, summary,
                problem_object, human_recommendation, mcp_output}
               ▸ Python path:  status/problem_object from Python; summary from LLM
               ▸ Fallback path: all fields from LLM
        │
        ▼
  yield SSE event: skill_done (all fields above)
        │
        ▼
Frontend _appendSkillCard(evt)
  Renders 4-section Skill Result Card (see §13)
```

#### Key Data Flows

| Step | Input | Output |
|------|-------|--------|
| B: DS fetch | `endpoint_url + params` | Raw JSON list |
| C: Sandbox | Python script + raw data | Arbitrary output (Standard Payload or raw) |
| D: Normalize | Sandbox output | Standard Payload `{dataset, ui_render, output_schema}` |
| E: Auto-chart | `dataset + ui_render_config` | Plotly JSON string (if `chart_data` was null) |
| F: Python sandbox | `generated_code + mcp_outputs` | `{status, diagnosis_message, problem_object}` |
| F summarize | Python result + diagnostic_prompt | `{summary}` (LLM-generated narrative) |
| F' LLM fallback | `diagnostic_prompt + MCP output` | `{status, conclusion, evidence, summary, problem_object}` |

#### Parameter Mapping

Event parameters → MCP input parameters via `skill.param_mappings`:
```json
{"mcp_field": "event_param_key"}
```
e.g. `{"chart_name": "chart_name"}` maps the event's `chart_name` attribute to the MCP script's expected input.

---

All legacy agent skills inherit from `BaseMCPSkill` (`app/skills/base.py`) and are registered in `SKILL_REGISTRY` (dict keyed by tool name).

### 7.1 `mcp_event_triage` — EventTriageSkill

**Must be called first** by the diagnostic agent.

Input: `{user_symptom: str}`

Output:
```json
{
  "event_id": "EVT-XXXXXXXX",
  "event_type": "SPC_OOC_Etch_CD|Equipment_Down|Recipe_Deployment_Issue|Unknown_Fab_Symptom",
  "attributes": {
    "symptom": "...", "urgency": "critical|high|medium|low",
    "lot_id": "...", "eqp_id": "...", "rule_violated": "...", ...
  },
  "recommended_skills": [...]
}
```

**Triage rules** (priority order):
1. SPC/AEI/CD anomaly → `SPC_OOC_Etch_CD` + 3 skills
2. Equipment down → `Equipment_Down` + EC check
3. Deployment/upgrade → `Recipe_Deployment_Issue` + recipe + APC
4. Unknown → `Unknown_Fab_Symptom` + EC check

### 7.2 `mcp_check_apc_params` — EtchApcCheckSkill

Input: `{target_equipment: str, target_chamber: str}`

Checks APC compensation parameter saturation.
Returns: `{apc_model_status: "SATURATED|OK", saturation_flag: bool, ...}`

### 7.3 `mcp_check_recipe_offset` — EtchRecipeOffsetSkill

Input: `{recipe_id: str, equipment_id: str}`

Audits recipe modification history (MES/RMS).
Returns: `{has_human_modification: bool, modification_count_7d: int, ...}`

### 7.4 `mcp_check_equipment_constants` — EtchEquipmentConstantsSkill

Input: `{eqp_name: str, chamber_name: str}`

Compares EC against golden baseline.
Returns: `{hardware_aging_risk: "LOW|MEDIUM|HIGH", out_of_spec_count: int, ec_comparison: [...]}`

### 7.5 `ask_user_recent_changes` — AskUserRecentChangesSkill

Input: `{topic: str, time_window: str}`

Passive skill — generates structured questions for the human operator (no API call).

---

## 8. Frontend Assets

**Directory**: `static/`

| File | Description |
|------|-------------|
| `index.html` | Main SPA entry point. Sidebar nav (9 items; 診斷站 is default), slash command menu (`/`), copilot chat panel, help chat panel (`?`), Agent Console. |
| `style.css` | Light theme: white/slate-50 content cards, dark sidebar (`bg-slate-800`). `.slash-menu`, `.copilot-tool-tag`, SSE card styles. |
| `app.js` | Copilot intent parsing, SSE streaming (Fetch + ReadableStream), event diagnosis tabs, slot filling state, `_parseCopilotChunk()`, `_parseSSEChunk()`. Agent Console: `_diagLogLine()`, `_diagConsoleExpand/Collapse/Toggle/Clear()`. |
| `builder.js` | Nested Builder, MCP Builder (two-state list+editor, `_mcpOpenEditor/BackToList/TryRun/Save`), Skill Builder (two-state list+editor, `_skOpenEditor/BackToList/TryRun/Save`). |

#### 主要 JS 模組結構（v13.5）

| 函式 / 模組 | 位置 | 職責 |
|------------|------|------|
| `_createWorkspaceTab` | app.js | 在 #ws-data-tab-bar 新增 tab；面板 append 至 #ws-data-content |
| `_activateWorkspaceTab` / `_closeWorkspaceTab` | app.js | Tab 切換 / 關閉 |
| `_renderAiAnalysisPanel` | app.js | 將 AI 分析 Markdown 渲染至右側 #ws-analysis-content |
| `_renderCopilotMcpPanel` | app.js | MCP 查詢結果 → workspace tab |
| `_renderCopilotSkillPanel` | app.js | Skill 診斷結果 → workspace tab |
| `_skFetchPreview` | builder.js | Skill Builder 撈取預覽；含 data_subject 名稱回退 |
| `_mcpOpenEditor` | builder.js | MCP 編輯器開啟；含 system_mcp_id 名稱回退 |

### 8.1 Nav Sidebar Order (v13)

| # | ID | 頁面 | 預設 |
|---|----|------|------|
| 1 | `nav-diagnose` | 診斷站 (Copilot + Event) | ✅ active |
| 2 | `nav-dashboard` | 戰情指揮中心 | |
| 3 | `nav-nested-builder` | 巢狀建構器 | |
| 4 | `nav-data-subjects` | Data Subjects | |
| 5 | `nav-mcp-builder` | MCP Builder | |
| 6 | `nav-skill-builder` | Skill Builder | |
| 7 | `nav-event-types` | Event Types | |
| 8 | `nav-generated-events` | 自動生成警報 | |
| 9 | `nav-system-params` | 系統參數 | |

> 排程巡檢管理 (`nav-routine-checks`) 已從 sidebar 移除（頁面 HTML 保留，可直接呼叫 `switchView('routine-checks')`）。

### 8.2 Skill Builder & MCP Builder Page States (v13)

兩個 Builder 頁面均採**兩段式**設計：

**List State** (預設): 卡片列表 + 右上角「新增」按鈕。
- Skill: `#sk-list-state` — 點擊卡片或「新增」→ `_skOpenEditor(id|null)`
- MCP: `#mce-list-state` — 點擊卡片或「新增」→ `_mcpOpenEditor(id|null)`

**Editor State**: 全頁 L/R 分割（`xl:flex-row`），無 drawer。
- 左側：設定卡片（Skill: L2 purple + L3 emerald；MCP: L3 emerald）
- 右側：Terminal Logs + Execution Report 雙頁籤
- 標題列：`← 返回列表 | 名稱 | 💾 儲存 | ▶ Try Run`
- IDs: `#sk-editor` / `#mcp-editor`

### 8.3 Agent Console (v13)

位於診斷站 `#report-panel` 底部，ID `#diag-console`。

| 狀態 | 高度 | 觸發 |
|------|------|------|
| 隱藏 | `0px` | 初始 |
| 展開 | `218px` | 第一條 log 自動展開 |
| 收縮 | `34px`（僅 header） | 點擊 `▲` toggle |

**Log 函數**: `_diagLogLine(icon, text, color)` — 帶時間戳、自動 scroll。
**鉤入點**:
- `_sendCopilotMessage` — 使用者送出訊息（灰色）
- `_handleCopilotEvent` — `thinking`、`mcp_result`（綠）、`skill_result`（綠/黃）、`error`（紅）、`done`
- `_launchEventDiagnosis` — SSE `start`、`skill_start`、`skill_done`（含 error）、`done`

### 8.4 Plotly Chart Rendering Rules (v13)

所有 `Plotly.newPlot` 呼叫使用以下 margin/legend 規則（共 4 處）：

```javascript
const mergedMargin = Object.assign({ t: 40, b: 40, l: 50, r: 20 }, specLayout.margin || {});
if (specLayout.title && mergedMargin.t < 55) mergedMargin.t = 55;
const hasHorizLegend = specLayout.legend?.orientation === 'h';
if (hasHorizLegend && mergedMargin.b < 100) mergedMargin.b = 100;
const legendOverride = hasHorizLegend ? { legend: { ...specLayout.legend, y: -0.28, x: 0, xanchor: 'left' } } : {};
```

LLM prompt 亦規定 `fig.update_layout` 預設使用 `height=360, margin.t=55, margin.b=100, legend(orientation='h', y=-0.28)`。

**Key frontend patterns**:
- SSE via `fetch()` + `ReadableStream` (not `EventSource` — lacks `Authorization` header support)
- Copilot SSE format: `data: {...}\n\n` (type inside JSON)
- Event-driven SSE format: `event: TYPE\ndata: {...}\n\n`

---

## 9. Dependencies

Key packages from `requirements.txt`:

| Category | Package | Version | Notes |
|----------|---------|---------|-------|
| Web | `fastapi` | ≥0.111.0 | |
| Web | `uvicorn[standard]` | ≥0.30.0 | |
| DB | `sqlalchemy[asyncio]` | ≥2.0.30 | |
| DB | `alembic` | ≥1.13.0 | |
| DB | `aiosqlite` | ≥0.20.0 | SQLite async driver |
| DB | `asyncpg` | ≥0.30.0 | PostgreSQL async driver |
| Validation | `pydantic[email]` | ≥2.10.0 | v2 required |
| Config | `pydantic-settings` | ≥2.5.0 | |
| Auth | `python-jose[cryptography]` | ≥3.3.0 | |
| Auth | `bcrypt` | ≥4.2.0 | |
| AI | `anthropic` | ≥0.40.0 | Pydantic v2 compat required |
| Sandbox | `pandas` | ≥2.2.0 | |
| Sandbox | `plotly` | ≥5.22.0 | |
| Scheduler | `apscheduler` | ≥3.10.0 | |
| HTTP | `httpx` | ≥0.27.0 | |
| Test | `pytest-asyncio` | ≥0.23.0 | `asyncio_mode = auto` |

---

## 10. Database Migrations

**Directory**: `alembic/versions/`

| Revision | Date | Description |
|----------|------|-------------|
| `3ece7dfc2a87` | 2026-03-04 | Initial schema — all 9 tables |

**Run in production**:
```bash
cd fastapi_backend_service
alembic upgrade head
```

**Development**: `init_db()` auto-runs on startup (creates schema, no Alembic needed).

---

## 11. Response Formats

### StandardResponse (all endpoints)

```json
{
  "status": "success|error",
  "message": "Human-readable message",
  "data": {},
  "error_code": null
}
```

### HealthResponse

```json
{
  "status": "ok|degraded",
  "version": "1.0.0",
  "database": "connected|unavailable",
  "timestamp": "2026-03-04T12:00:00Z"
}
```

### SSE — Event-Driven Diagnostic

```
event: session_start
data: {"event_type": "...", "event_id": "..."}

event: skill_start
data: {"skill_id": 1, "skill_name": "...", "mcp_name": "..."}

event: skill_done
data: {
  "skill_id": 1,
  "skill_name": "檢查SPC 是否連續異常",
  "mcp_name": "SPC CD Chart Query",
  "status": "NORMAL|ABNORMAL",
  "conclusion": "一句話結論",
  "evidence": ["具體觀察 1", "具體觀察 2"],
  "summary": "2–3 句完整說明",
  "problem_object": {"tool": ["TETCH10"], "recipe": "ETH_RCP_10"},
  "human_recommendation": "聯繫製程工程師排查 TETCH10",
  "mcp_output": {
    "output_schema": {...},
    "dataset": [...],
    "ui_render": {"type": "chart", "chart_data": "<Plotly JSON>"}
  },
  "error": null
}

event: done
data: {}
```

#### `skill_done` Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | `NORMAL\|ABNORMAL` | Binary diagnostic result |
| `conclusion` | string | One-sentence result (LLM-generated) |
| `evidence` | string[] | Bullet-point observations supporting conclusion |
| `summary` | string | 2–3 sentence integrated explanation |
| `problem_object` | object | Identified abnormal entities (tool, recipe, lot, etc.); `{}` when NORMAL |
| `human_recommendation` | string | Suggested action written by domain expert (from Skill DB field); empty when none configured |
| `mcp_output` | Standard Payload | Raw MCP execution result (`dataset` + `ui_render` with chart_data) |

### SSE — Copilot Chat

```
data: {"type": "thinking", "message": "..."}
data: {"type": "intent_parsed", ...}
data: {"type": "slot_fill_request", "missing_params": [...], "reply_message": "..."}
data: {"type": "mcp_result", "mcp_name": "...", "output": {...}, ...}
data: {"type": "skill_result", "skill_name": "...", "status": "...", ...}
data: {"type": "done"}
```

---

## 12. Running the Service

### Development

```bash
cd fastapi_backend_service
pip install -r requirements.txt
uvicorn main:app --reload
```

**Required `.env`** (create in `fastapi_backend_service/`):
```env
ANTHROPIC_API_KEY=sk-ant-...
SECRET_KEY=<generate with: openssl rand -hex 32>
DATABASE_URL=sqlite+aiosqlite:///./dev.db
```

### Tests

```bash
cd fastapi_backend_service
pytest --cov=app --cov-report=term-missing
```

### Production (via GitHub Actions CD)

Push to `main` branch → `.github/workflows/deploy.yml` SSH-deploys to EC2:
1. `git pull origin main`
2. `npm run build` (frontend)
3. `pip install -r requirements.txt`
4. `alembic upgrade head`
5. `nohup uvicorn main:app --host 0.0.0.0 --port 8000`

---

## 13. Skill Result Card UI (v13.0)

When a Skill executes, the right-side report panel renders a per-skill tab card. Each card has the following layout:

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚙️ [Skill Name]     [MCP Name]              ⚠ ABNORMAL / ✓ NORMAL │
├─────────────────────────────────────────────────────────────────┤
│ [LLM Summary]                                                    │
│   e.g. "偵測到 TETCH10 搭配 ETH_RCP_10 之 CD 值 47.5 nm 超出     │
│         3-sigma 管制上限，為所有資料點中偏離最嚴重者。"              │
│                                                                  │
│ 🎯 異常物件                                                        │
│   tool: TETCH10, TETCH09                                        │
│   recipe: ETH_RCP_10                                            │
│   measurement: CD value 47.5 nm                                 │
│                                                                  │
│ 💡 建議動作：聯繫製程工程師排查 TETCH10 是否有硬體異常            │  ← suggestion action
│                                                                  │
│ ┌──────────────┬──────────────┐                                  │
│ │ 📊 趨勢圖 ▐  │  📋 數據     │  ← MCP evidence tabs             │
│ ├──────────────┴──────────────┤                                  │
│ │  [Plotly trend chart]        │  ← tab 1 active by default      │
│ └─────────────────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 4 Display Sections

| # | Section | Field Source | Always Shown? |
|---|---------|--------------|---------------|
| 1 | **LLM Summary** | `summary` (LLM-generated from Python result) | Yes (falls back to `conclusion` if empty) |
| 2 | **Identified abnormal objects** | `problem_object` (Python sandbox result) | Only when non-empty |
| 3 | **Suggestion action** | `human_recommendation` (expert DB field) | Only when ABNORMAL + field is set |
| 4 | **MCP evidence tabs** | `mcp_output` (Charting + Summary Data) | Only when `mcp_output` has data |

### Diagnosis Source Priority

| Path | Trigger | Status/problem_object Source | Summary Source |
|------|---------|------------------------------|----------------|
| **Python code** (preferred) | `skill.last_diagnosis_result.generated_code` exists | Python `diagnose(mcp_outputs)` sandbox | LLM `summarize_diagnosis()` |
| **LLM fallback** | No `generated_code` stored | LLM `try_diagnosis()` | LLM `try_diagnosis()` |

### Evidence Tabs (section 4)

Same as MCP result evidence tabs (§12 MCP Result Display):
- **📊 Charting tab** (shown when `chart_data` is present after auto-generation)
- **📋 Summary Data tab** (shown when `dataset` exists and `_is_processed=true`)
- **📄 Raw Data tab** (when `_is_processed=false`)
- Call params chip bar at top (from `_call_params` dict)

### Auto-Chart Fallback (`_auto_chart`)

When `mcp_output.ui_render.chart_data` is null after script execution, `_auto_chart(dataset, ui_render_config)` generates a Plotly `Scatter` chart from the dataset using the MCP's `ui_render_config` (x_axis, y_axis, series keys). This applies in:
- Event-driven diagnosis pipeline (`event_pipeline_service._run_skill`)
- Copilot direct MCP execution (`copilot_service._execute_mcp`)
- MCP Builder re-open: `_buildChartFromDataset()` in `builder.js` regenerates chart client-side from stored dataset + `ui_render_config`, bypassing any stale `chart_data` stored in `sample_output`.

---

## 14. Agent v13 架構

### 13.1 AgentOrchestrator

檔案：`app/services/agent_orchestrator.py`

5-Stage 迴圈：
1. **Context Load** — Soul + UserPref + RAG 組裝 system prompt
2. **LLM Call** — `anthropic.messages.create(tools=TOOL_SCHEMAS, ...)`
3. **Tool Execute** — Pre-flight validate → ToolDispatcher.execute()
4. **Synthesis** — `stop_reason=end_turn` → emit synthesis event
5. **Memory Write** — ABNORMAL 診斷自動存入 agent_memories

### 13.2 Pre-flight Validation

函式：`_preflight_validate(db, tool_name, tool_input)`

攔截規則：
- `execute_mcp`: mcp_id 不存在 → 錯誤；system MCP 直接呼叫時檢查自身 input_schema；custom MCP 檢查 parent system MCP input_schema；params={} 但有 input fields → 要求確認
- `execute_skill`: skill_id 不存在 → 錯誤

### 13.3 Session History Management

- 每次對話結束後 `messages[-20:]` 截斷
- `_clean_history_boundary()` 掃描截斷後的開頭，移除孤立的 `user(tool_result)` + 對應 `assistant` message，防止 Anthropic API 400 invalid_request_error
- `_sanitize_history()` 截斷舊 session 中超大的 tool_result content（>2000 chars）

### 13.4 Internal URL Rule

所有 service 層的內部 httpx 呼叫（system MCP endpoint fetch）必須使用：
```python
if endpoint_url.startswith("/"):
    url = "http://127.0.0.1:8000" + endpoint_url  # 不走 nginx
```

### 13.5 Split-Screen Dashboard Layout

```
#view-diagnose (flex row)
├── #diag-console (left: chat + agent console)
└── #ws-split-container (right: flex row, flex-1)
    ├── #ws-data-pane (flex:7)
    │   ├── #ws-data-tab-bar (hidden when ≤1 tab)
    │   └── #ws-data-content (overflow-y-auto)
    └── #ws-analysis-pane (flex:3)
        └── #ws-analysis-content (.ai-analysis-body, 12px)
```

### 13.6 Tool Schemas

| Tool | 用途 |
|------|------|
| `execute_skill` | 執行 Skill；回傳 llm_readable_data (status/diagnosis_message/problematic_targets) |
| `execute_mcp` | 執行 MCP (system + custom)；回傳 dataset preview + mcp_name |
| `list_skills` | 列出所有 public Skill |
| `list_mcps` | 列出 custom MCP |
| `list_system_mcps` | 列出 system MCP |
| `draft_skill` | 建立 Skill 草稿 (待人工審核) |
| `draft_mcp` | 建立 MCP 草稿 |
| `patch_skill_raw` | 以 OpenClaw Markdown 直接修改 Skill |
| `search_memory` | 搜尋 RAG 長期記憶 |
| `update_user_pref` | 更新用戶偏好 |
