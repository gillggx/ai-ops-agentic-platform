# Glass Box AI Diagnostic Platform — System Specification (Latest)

**Version**: v12.0
**Last Updated**: 2026-03-04
**Status**: Active Development — Phases 1–14 Complete

## Changelog

| Version | Date | Changes |
|---------|------|---------|
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

---

## 1. System Overview

**Project Root**: `fastapi_backend_service/`
**Application Name**: Glass Box AI Diagnostic Platform
**Version**: 1.0.0 (app), v11.0 (spec)

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

### 4.14 Mock Data (`/mock`)

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

All skills inherit from `BaseMCPSkill` (`app/skills/base.py`) and are registered in `SKILL_REGISTRY` (dict keyed by tool name).

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
| `index.html` | Main SPA entry point. Sidebar nav, slash command menu (`/`), copilot chat panel, help chat panel. |
| `style.css` | Light theme: white/slate-50 content cards, dark sidebar (`bg-slate-800`). `.slash-menu`, `.copilot-tool-tag`, SSE card styles. |
| `app.js` | Copilot intent parsing, SSE streaming (Fetch + ReadableStream), event diagnosis tabs, slot filling state, `_parseCopilotChunk()`, `_parseSSEChunk()`. |
| `builder.js` | MCP Builder UI (script generation, try-run, output preview) and Skill Builder UI (param mapping, diagnostic prompt editor). |

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

## 13. Skill Result Card UI (v12.0)

When a Skill executes, the right-side report panel renders a per-skill tab card. Each card has the following layout:

```
┌─────────────────────────────────────────────────────────────────┐
│ ⚙️ [Skill Name]     [MCP Name]              ⚠ ABNORMAL / ✓ NORMAL │
├─────────────────────────────────────────────────────────────────┤
│ [Diagnosis Message]                                              │
│   e.g. "3-sigma 最差機台與配方異常條件成立，TETCH10 搭配                │
│         ETH_RCP_10 之 CD 值 47.5 nm 為所有資料點中偏離管制最嚴重者"   │
│                                                                  │
│ 🎯 異常物件                                                        │
│   tool: TETCH10, TETCH09                                        │
│   recipe: ETH_RCP_10                                            │
│   measurement: CD value 47.5 nm                                 │
│                                                                  │
│ • UCL=46.5 nm, LCL=43.5 nm, 管制中心值 45.0 nm                   │  ← evidence bullets
│ • 各資料點偏離中心值之 sigma 倍數：TETCH10 (+5.0σ), ...           │
│ • OOC 記錄共 4 筆：TETCH10, TETCH09, TETCH03, TETCH01            │
│                                                                  │
│ ┌──────────────┬──────────────┐                                  │
│ │ 📊 趨勢圖 ▐  │  📋 數據     │  ← evidence tabs (chart | data)  │
│ ├──────────────┴──────────────┤                                  │
│ │  [Plotly trend chart]        │  ← tab 1 active by default      │
│ └─────────────────────────────┘                                  │
│                                                                  │
│ 💡 建議動作：聯繫製程工程師排查 TETCH10 是否有硬體異常            │  ← suggestion action
└─────────────────────────────────────────────────────────────────┘
```

### 5 Display Sections

| # | Section | Field Source | Always Shown? |
|---|---------|--------------|---------------|
| 1 | **Diagnosis message** | `conclusion` (LLM) | Yes |
| 2 | **Identified abnormal objects** | `problem_object` (LLM) | Only when non-empty |
| 3 | **Evidence bullets** | `evidence[]` (LLM) | Only when non-empty |
| 4 | **Chart tab / Data tab** | `mcp_output` | Only when `mcp_output` has data |
| 5 | **Suggestion action** | `human_recommendation` (expert DB field) | Only when ABNORMAL + field is set |

### Evidence Tabs (section 4)

- **📊 趨勢圖 tab** (default active): Renders a Plotly interactive chart from `mcp_output.ui_render.chart_data`.
  If the processing script returned `chart_data=null`, the backend `_auto_chart()` function auto-generates a chart from `mcp_output.dataset` + MCP's `ui_render_config`.
- **📋 數據 tab**: Shows the raw dataset table (up to 15 rows).
- If no chart_data exists after auto-generation, only the 📋 Data table is shown without tabs.

### LLM Diagnosis Output Format

`try_diagnosis()` in `mcp_builder_service.py` prompts the LLM to return:
```json
{
  "status": "NORMAL|ABNORMAL",
  "conclusion": "一句話結論",
  "evidence": ["具體觀察 1", "具體觀察 2"],
  "summary": "2–3 句完整說明",
  "problem_object": {
    "tool": ["TETCH10", "TETCH09"],
    "recipe": "ETH_RCP_10"
  }
}
```
`problem_object` contains identified abnormal entities keyed by category (tool, recipe, lot, measurement, etc.).
`human_recommendation` is **not** LLM-generated — it is written by the domain expert in the Skill definition and stored in the `skill_definitions.human_recommendation` column.

### Auto-Chart Fallback (`_auto_chart`)

When `mcp_output.ui_render.chart_data` is null after script execution, `_auto_chart(dataset, ui_render_config)` generates a Plotly `Scatter` chart from the dataset using the MCP's `ui_render_config` (x_axis, y_axis, series keys). This applies in:
- Event-driven diagnosis pipeline (`event_pipeline_service._run_skill`)
- Copilot direct MCP execution (`copilot_service._execute_mcp`)
- MCP Builder re-open: `_buildChartFromDataset()` in `builder.js` regenerates chart client-side from stored dataset + `ui_render_config`, bypassing any stale `chart_data` stored in `sample_output`.
