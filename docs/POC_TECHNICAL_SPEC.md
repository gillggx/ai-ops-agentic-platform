# Skill Library Platform — Technical Build Specification

> **Audience:** an engineering team (or AI coding agent) rebuilding this
> platform from scratch. This spec is derived from the actual POC codebase,
> not from intent. It is dense on purpose — every section is a contract you
> can implement against.
>
> **Companion docs:** `POC_PRODUCT_SPEC.html` (functional / stakeholder view),
> `POC_DEPLOYMENT_SPEC.html` (ops), `POC_HANDOVER_PLAN.html` (DevOps handover).
> Architecture/principles source of truth lives in `CLAUDE.md`.
>
> Generated 2026-06-24.

---

## 0. What you are building

An **AI analysis skill library** for semiconductor fab operations. A process
engineer describes an ops question in natural language; an LLM agent turns it
into a **data-analysis pipeline** (a DAG of typed blocks), executes it against
external data sources, and returns charts / tables / verdicts. Good pipelines
are **published as Skills** that the whole team re-runs with a form.

The hard, novel part is the **agent that builds pipelines reliably**. Everything
else (registry, execution, auth, UI) is conventional CRUD + a DAG executor. Build
the agent last, after the substrate is solid.

### The six core features (product surface)
1. **L1 Library** — browse/search/run published Skills + browse the block catalog.
2. **L2 Authoring** — build a Skill two ways: natural-language (Glass Box agent) or manual canvas.
3. **L3 Try-Run** — execute a draft against live data, render result, confirm before publish.
4. **Block Docs + Advisor** — self-documenting block catalog + a Q&A assistant about blocks.
5. **Build Trace** — full record of how the agent built each pipeline, for debug.
6. **System MCP** — register external HTTP services as data sources (+ auto-derive blocks/skills).

---

## 1. System architecture

Four services + one shared-types package. Single-host systemd today; each service
is independently containerizable (K8s future).

```
┌──────────────────────────────────────────────────────────────────────┐
│ aiops-app  :8000   Next.js (App Router, standalone, TypeScript)        │
│   UI rendering + /api/* proxy ONLY. No business logic, no direct DB.   │
└───────────────┬──────────────────────────────────────────────────────┘
                │  every backend call goes through /api/* proxy routes
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ java-backend :8002  Spring Boot 3.5.14 / Java 17                       │
│   SOLE owner of PostgreSQL+pgvector. Auth (JWT). Business CRUD.        │
│   /api/v1/*  user-facing (JWT)   ·   /internal/*  service (X-token)    │
│   Bridges SSE to the sidecar (reactive Flux → MVC SseEmitter).         │
└───────┬───────────────────────────────────────────┬──────────────────┘
        │ JavaAPIClient (/internal/*, X-Internal-Token)                  │
        ▼                                            │ PostgreSQL JDBC
┌────────────────────────────────────────────┐      ▼
│ python_ai_sidecar :8050  FastAPI+LangGraph  │   ┌──────────────────┐
│   ALL agents live here (chat + builder).    │   │ PostgreSQL +     │
│   56 block executors run in-process.        │   │ pgvector         │
│   NEVER opens Postgres — only calls Java.   │   └──────────────────┘
│   Calls external data via System MCP (HTTP).│
└───────────────┬─────────────────────────────┘
                │ HTTP (System MCP dispatch)
                ▼
        External data sources (registered as System MCPs)
        (In the full product: ontology_simulator :8012. In the POC it
         is stripped — data comes from real external HTTP APIs.)

aiops-contract  — dual-language (TS + Python) shared output schema
                  (AIOpsReportContract) for Agent ↔ Frontend.
```

### Hard architectural boundaries (do not violate)
- Frontend never touches Postgres / sidecar / data sources directly — only `/api/*` proxies.
- Java is the **only** DB owner. The sidecar reaches all state through `JavaAPIClient` → `/internal/*`.
- The sidecar is the **only** home for agents and block execution.
- Flow control lives in **graph nodes**, never in LLM prompts (see §6.4). This is the single most important design rule; violating it is why earlier iterations were unmaintainable.

---

## 2. Tech stack & cross-cutting conventions

| Layer | Choice | Notes |
|---|---|---|
| Frontend | Next.js App Router, TypeScript, `output: "standalone"`, inline styles | NextAuth v5. No Tailwind/CSS-modules. |
| Backend | Spring Boot 3.5.14, Java 17 (Temurin), Maven | Thin controller + focused service. |
| DB | PostgreSQL + pgvector (1024-dim) | Java-owned. Flyway present but **disabled in prod** (apply `V*.sql` via manual `psql`). |
| Agent sidecar | Python 3.11, FastAPI, LangGraph | In-process block execution. |
| LLM | OpenAI-compatible via OpenRouter (KIMI K2.5 default); Anthropic native optional | Single env switch (`LLM_PROVIDER` / `OLLAMA_MODEL`). |
| Node | 20.18 | |

### Wire format — **snake_case everywhere**
Java Jackson is configured `SNAKE_CASE` on output + case-insensitive on input.
TypeScript interfaces and POST bodies MUST use snake_case keys. camelCase keys
that don't match are **silently dropped** → HTTP 200 + null fields (a real
foot-gun; many "the button does nothing" bugs trace to this).

### Async-first
All DB and HTTP operations are async. Never swallow exceptions — log with
enough context to debug, return a meaningful error. Narrow catches to the
actual exception type (never bare `catch(Exception)`).

### pgvector write rule
JPA binds `String` as VARCHAR; Postgres refuses implicit varchar→vector cast.
Embedding columns are `@Column(insertable=false, updatable=false,
columnDefinition="vector(1024)")` so JPA INSERT/UPDATE omit them; writes go
through a native `@Query` with `CAST(:vec AS vector)`. Reads work via normal JPA.

### Ports (env-driven, never hardcode)
EC2 prod: app 8000, java 8002, sidecar 8050, (simulator 8012 — full product only).
Read all URLs/ports from `.env` / ConfigMap. Acceptable fallback pattern:
`os.environ.get("XXX_URL", "http://localhost:80NN").rstrip("/")`.

---

## 3. Data model (PostgreSQL)

Java JPA entities under `com.aiops.api.domain` are the canonical schema (the
Flyway baseline `V0` is a no-op `SELECT 1;` — original tables were adopted from
a decommissioned Python service). PKs are `BIGINT IDENTITY` unless noted. There
are **no Java enums** — enumerated values are `String` columns with documented
domains. **JSON payloads are stored as `text`** (repo convention to stop JPA
over-interpreting). An `Auditable` superclass adds `created_at` + `updated_at`.

### 3.1 Core tables (build these first)

**`pb_blocks`** — the block catalog (the LLM's entire knowledge of a block).
`UNIQUE(name, version)`.
| col | type | domain / note |
|---|---|---|
| name | varchar(128) | stable block id, e.g. `block_filter` |
| category | varchar(32) | `source` \| `transform` \| `output` \| `logic` \| `check` |
| version | varchar(32) | `"1.0.0"` |
| status | varchar(16) | `draft` \| `active` \| `deprecated` (also `production` used by validator) |
| description | text | **single source of truth** (structured prose, see §5.1) |
| input_schema | text(JSON) | `[{port,type,columns?}]` |
| output_schema | text(JSON) | `[{port,type}]` |
| param_schema | text(JSON) | JSON-Schema-ish `{type:object, properties, required}` |
| implementation | text(JSON) | `{type:"python", ref:"...:XxxExecutor"}` or `{type:"mcp_proxy", mcp_name, delegate_block}` |
| examples | text(JSON) | `[{params, desc}]` |
| output_columns_hint | text(JSON) | `[{name,type,description?,when_present?}]` |
| is_custom | bool | |
| source | varchar | `manual` \| `mcp_auto` (V54) |
| source_mcp_id | bigint → mcp_definitions | FK ON DELETE SET NULL |
| created_by / approved_by | bigint | |

**`pb_pipelines`** — a pipeline (a Skill's implementation).
| col | type | domain |
|---|---|---|
| name | varchar(128) | |
| description | text | |
| status | varchar(20) | `draft`→`validating`→`locked`→`active`→`archived` |
| pipeline_kind | varchar(20) | `auto_patrol` \| `auto_check` \| `skill` \| `diagnostic`(legacy) |
| version | varchar(32) | |
| pipeline_json | text(JSON) | the DAG (see §5.4) |
| usage_stats / auto_doc | text(JSON) | |
| created_by / approved_by / parent_id / parent_skill_doc_id | bigint | |

**`pb_published_skills`** — published Skill registry entry. `slug` unique;
`UNIQUE(pipeline_id, version)`.
| col | type | domain |
|---|---|---|
| pipeline_id / pipeline_version | bigint / varchar | |
| slug | varchar(80) | unique |
| name | varchar(128) | |
| use_case / when_to_use / inputs_schema / outputs_schema / tags / example_invocation | text | |
| status | varchar(16) | `active` \| `retired` |
| source / source_mcp_id | | `manual` \| `mcp_auto` |

**`skill_definitions`** — higher-level skill metadata (triggers). `name` unique.
trigger_mode `schedule|event|both`; source `legacy|rule|auto_patrol|skill`;
columns: description, trigger_event_id, steps_mapping, input_schema,
output_schema, pipeline_config, binding_type, auto_check_description,
visibility, trigger_patrol_id, created_by, is_active.

**`skill_documents`** — Phase-11 skill authoring docs. `slug` unique. stage
`patrol|diagnose`; status `draft|stable`; columns: title, version, domain,
description, author_user_id, trigger_config, steps, test_cases, stats,
confirm_check.

**`mcp_definitions`** — external data source registry. `name` unique.
| col | type | domain |
|---|---|---|
| name | varchar(200) | unique, e.g. `get_process_info` |
| description | text not null | **SSOT** for the LLM |
| mcp_type | varchar(10) | `system` \| `custom` |
| api_config | text(JSON) | `{endpoint_url, method, headers}` |
| input_schema | text(JSON) | `[{name,type,required,description}]` |
| output_schema / sample_output / processing_script / processing_intent | text | custom-MCP fields |
| system_mcp_id | bigint | custom → its source system MCP |
| prefer_over_system / visibility | bool / varchar | |
| produces_block / produces_skill | bool | V54 derivative flags |
| block_generation_meta | text(JSON) | audit (prompt_version, model, tokens) |

**`block_docs`** — per-block markdown documentation. `UNIQUE(block_id, block_version)`.
cols: markdown (YAML frontmatter + body), sections, auto_generated, last_edited_by, last_edited_at.

### 3.2 Agent knowledge tables (pgvector) — created together in one migration
**`agent_knowledge`** — RAG planning/execution hints.
user_id, scope_type, scope_value, title, body, priority(`high`…),
`applies_to`(`plan`|`execute`|`both`), `always_on`(bool), active, source,
**`embedding vector(1024)` insertable=false updatable=false**, uses, last_used_at.
ivfflat cosine index on embedding.

**`agent_examples`** — few-shot. user_id, scope_*, title, input_text,
output_text, **embedding vector(1024)**, uses.

**`agent_directives`** — prompt directives. user_id, scope_type
(`global|skill|tool|recipe`), scope_value, title, body, priority, active,
source(`manual|auto-promoted`).

**`agent_lexicon`** — term normalization. `UNIQUE(user_id, term)`; standard, note, uses.

**`agent_directive_fires`** — telemetry.

### 3.3 Auth / audit / ops tables
**`users`** — username (uq), email (uq), display_name, hashed_password,
is_active, is_superuser, `roles text` (JSON list), oidc_provider, oidc_sub,
last_login_at. **`role_change_logs`** — target_user_id, actor_user_id,
old_roles, new_roles, reason, changed_at. **`agent_sessions`** (string PK
`session_id varchar(36)`, LangGraph checkpoint store), **`agent_drafts`**
(string PK), **`agent_feedback_log`** (UQ session+msg+user), **`audit_logs`**,
**`event_types`** (uq name), **`system_parameters`** (uq key),
**`user_preferences`** (uq user_id), **`pb_canvas_operations`** (Glass-Box op
log), **`pb_pipeline_runs`**, **`execution_logs`**.

(L4 tables — out of POC scope: `alarms`, `auto_patrols`,
`pipeline_auto_check_triggers`, `generated_events`, `notification_inbox`,
`personal_rule_fires`, `routine_checks`.)

**Note:** Build traces are NOT a DB table — the sidecar writes them to
`/tmp/builder-traces/*.json` (see §7.7).

---

## 4. Backend API contract (Java)

Two auth surfaces. **`/api/v1/*`** = user-facing, JWT, `@PreAuthorize` role
gates. **`/internal/*`** = service-to-service, `X-Internal-Token` (+ optional
caller-IP allow-list), called only by the sidecar's `JavaAPIClient`. All
responses wrap in `ApiResponse<T>` → `{ "data": ... }`. DTOs are Java `record`s
serialized to snake_case.

Role authorities: `ADMIN = hasRole('IT_ADMIN')`,
`ADMIN_OR_PE = hasAnyRole('IT_ADMIN','PE')`, `ANY_ROLE = all three`.
Role hierarchy `IT_ADMIN > PE > ON_DUTY` (Spring `RoleHierarchyImpl`).

### 4.1 Agent proxy (SSE bridge to sidecar)
Bridges reactive `Flux<ServerSentEvent>` from the sidecar → MVC `SseEmitter`
via a `SseEmitterBridge.bridge(flux, tag, timeout)` helper. JSON (non-stream)
endpoints `.block()` the Mono.

| Method + path | auth | forwards to sidecar |
|---|---|---|
| POST `/api/v1/agent/chat` (SSE) | ANY_ROLE | `/internal/agent/chat` — `{message, session_id, client_context, mode, pipeline_snapshot}` |
| POST `/api/v1/agent/build` (SSE) | ADMIN_OR_PE | `/internal/agent/build` — `{instruction, pipeline_id, pipeline_snapshot, trigger_payload}` |
| POST `/api/v1/agent/build/{confirm,plan-confirm,clarify-respond,handover,modify-request}` (SSE) | ADMIN_OR_PE | builder resume endpoints |
| POST `/api/v1/agent/chat/intent-respond` (SSE) | ANY_ROLE | chat clarify/judge resume |
| POST `/api/v1/agent/{pipeline/execute, pipeline/validate, sandbox/run}` | ADMIN_OR_PE | block the Mono |
| GET/POST `/api/v1/agent/sessions[...]` | ANY_ROLE | session list/get |
| POST `/api/v1/agent/feedback` | ANY_ROLE | thumbs ±1 (rating=-1 needs reason∈{data_wrong,logic_wrong,chart_unclear}) |

### 4.2 Catalog + registry (internal, read by sidecar)
- GET `/internal/blocks?category&status`, GET `/internal/blocks/{id}` → block DTO (snake_case of §3.1 pb_blocks).
- GET `/internal/mcp-definitions?mcp_type` (note: **not** `/internal/mcps`) → MCP DTO.
- GET `/internal/pipelines/{id}` + list. GET `/internal/skills` + POST `/internal/skills/by-slug/{slug}/run-system`.
- POST `/internal/published-skills/search` `{query, top_k}`.
- GET `/internal/block-docs` + `/internal/block-docs/{block_id}/{version}` (auto-gen docs).
- Agent-knowledge internal surface `/internal/agent-knowledge/*`:
  `directives/active`, `directives/{id}/fire`, `lexicon`,
  `knowledge/search` (`{user_id, query_vec, skill_slug, tool_id, recipe_id, layer, limit}`),
  PUT `knowledge/{id}/embedding` (native CAST write), `knowledge/use`,
  `knowledge/high-priority?layer&always_only`, `examples/search`,
  `examples/{id}/embedding`, `*/missing-embeddings`.
- GET `/internal/agent-context` (≤10 active alarms snapshot), GET/PUT `/internal/agent-sessions/{id}` (LangGraph checkpointer store, partial upsert).

### 4.3 User-facing CRUD
- `/api/v1/skills` (list/get ANY_ROLE; create/update/delete ADMIN_OR_PE) — dup name → 409.
- `/api/v1/skill-documents` (thin → SkillDocumentService): CRUD + confirm-check + bind-pipeline + steps + POST `/{slug}/run` (SSE, → SkillRunnerService, events step_start/step_done/done).
- `/api/v1/pipelines` (thin → PipelineService): CRUD, fork, runs, transition, archive, publish/draft-doc, publish, publish-auto-check. DELETE = ADMIN.
- `/api/v1/pipeline-builder/{blocks,validate,preview,execute}` — reads + forward-to-sidecar (16MB buffer).
- `/api/v1/published-skills` (list/get/by-slug; POST `/{id}/retire` ADMIN_OR_PE).
- `/api/v1/mcp-definitions` (CRUD; writes ADMIN). POST create: if `produces_block|produces_skill` → `MCPDerivativeService.createWithDerivatives` (atomic MCP+block+pipeline+skill); else plain insert. POST `/generate-derivatives` (proxy sidecar Haiku, no DB write), POST `/{id}/regenerate-derivatives`.
- `/api/v1/agent-knowledge`, `/api/v1/agent-directives`, `/api/v1/agent-lexicon`, `/api/v1/agent-examples` (full CRUD, ANY_ROLE).
- `/api/v1/block-docs` (GET/PUT).
- `/api/v1/admin/users` (class-level ADMIN): create (+SegregationOfDuties), list, PUT `/{id}/roles` `{roles, reason}` (writes role_change_logs), PUT `/{id}/active`, GET `/{id}/role-history`. Self-lockout guards.
- `/api/v1/auth/login` (permit-all, local JWT), GET/PUT `/me`, PUT `/me/password`. POST `/api/v1/auth/oidc-upsert` (shared-secret `X-Upsert-Secret`; match provider+sub→email→create with default ON_DUTY; issues local JWT).

### 4.4 Auth model (security filter chains)
Two `SecurityFilterChain`s ordered by `@Order`:
1. `securityMatcher("/internal/**")`, stateless. `X-Internal-Token` validated against config; grants `SERVICE_PYTHON_SIDECAR`. **Rebuilds the originating user** from forwarded `X-User-Id` / `X-User-Name` / `X-User-Roles` so audit logs capture the real user, not the sidecar.
2. Everything else, stateless. Permit-all: `/actuator/health`, `/api/v1/auth/login`, `/api/v1/auth/oidc-upsert`, `/api/v1/health`; `anyRequest().authenticated()`.

Mode-driven (`aiops.auth.mode`): `local` → JWT (HMAC256, ≥32-char secret, claims `roles`+`user_id`); `oidc` → OAuth2 resource server (Azure AD JWKS). A `SharedSecretAuthFilter` accepts `Bearer <shared-secret>` as a synthetic IT_ADMIN (legacy frontend `INTERNAL_API_TOKEN` compat); it overrides `shouldNotFilterAsyncDispatch()=false` so the security context survives SSE async re-dispatch. **SegregationOfDuties**: IT_ADMIN+PE forbidden together; ON_DUTY exclusive; ≥1 role required.

### 4.5 Shared helpers (build these, don't re-implement per call-site)
`JsonUtils.{parseObject→{},parseListOfObjects→[],safeWrite→null,asMap}`
(catch `JsonProcessingException` only). `SseEmitterBridge.bridge(flux, tag,
timeoutMs)` (default 10min; disposes the reactor subscription on
timeout/error/complete). `RequestBodyAccess.{pickAlias, requireAlias→400,
asLong, asBool}` for endpoints accepting both camel/snake. `ApiResponse`
envelope, `ApiException` + `@ControllerAdvice` → HTTP status.

---

## 5. The block + pipeline execution system (the substrate)

This is the deterministic engine the agent drives. Build and test it **before**
the agent — the agent is only as good as the blocks it has.

### 5.1 Block spec schema
Each block is a spec dict (canonical list lives in
`pipeline_builder/seed.py:_blocks()`, seeded into `pb_blocks`, re-read at
runtime via the registry). Fields and their roles:

| field | role |
|---|---|
| `name`, `version` | natural key; `name` is referenced by pipeline nodes |
| `category` | `source`/`transform`/`output`/`logic`/`check` — drives validator endpoint rules + UI grouping |
| `status` | `production`/`deprecated` |
| `description` | **the single source of truth the LLM reads.** Structured prose: `== What ==`, `== When to use ==` (with ✅/❌ examples), `== Params ==`, `== Output ==`, `== Common mistakes ==`, `== Errors ==`. The agent picks blocks and writes params from this text alone — it never sees executor source. |
| `input_schema` / `output_schema` | declared ports `[{port,type,columns?}]`. Source blocks have `input_schema=[]`. Logic blocks emit `triggered`(bool)+`evidence`(df). Chart blocks emit `chart_spec`(dict). |
| `param_schema` | `{type:object, properties:{...}, required:[...]}`. Properties carry `type`/`enum`/`default`/`description` + custom UI hints `x-column-source`, `x-suggestions`. Validator C6 + UI Inspector both read it. |
| `implementation` | `{type:"python", ref:"...:Executor"}` or `{type:"mcp_proxy", mcp_name}` (V54) |
| `produces` | **phase-matching metadata.** `covers`: list of phase kinds this block satisfies (`raw_data`/`transform`/`scalar`/`verdict`/`chart`/`table`/`alarm`). `outcome_extractors`: `[{key, from_port, json_path, type}]` declarative result extraction. Composite panels split into `covers_output` vs `covers_internal`. |
| `examples` | `[{params, desc}]` — concrete fillings; read by LLM + shown in BlockDocsDrawer |
| `output_columns_hint` | `[{name,type,description?,when_present?}]` — incl. conditional (`when_present:"object_name=APC"`) + dynamic (`apc_<param>`) columns |
| `column_docs` | richer v30 per-column doc `[{col,type,what}]` injected into agent prompts |
| `meta.standalone_capable` | opts a composite block out of the orphan validator |

**Critical invariant:** `description` / `param_schema` / `examples` must stay
in sync because the Glass-Box builder, the Block Advisor, and the user-facing
BlockDocsDrawer all read them. There is no other documentation. Changing block
behavior means changing all three.

### 5.2 Executor contract
`BlockExecutor(ABC)` (`pipeline_builder/blocks/base.py`):
```python
class BlockExecutor(ABC):
    block_id: str  # must be set; empty → RuntimeError
    @abstractmethod
    async def execute(self, *, params: dict, inputs: dict,
                      context: ExecutionContext) -> dict[str, Any]: ...
```
- `params`: `$input`-resolved + param_schema-validated user params.
- `inputs`: `{dest_port: upstream_value}`. The standard data port is
  `inputs["data"]`, a **pandas DataFrame** (records-as-rows; values may be
  nested dict/list under object-native mode).
- returns `{port_name: value}` — keys must match declared `output_schema`.
  Data ports return `pd.DataFrame`; chart blocks return `{"chart_spec": dict}`;
  logic blocks return `{"triggered": bool, "evidence": df}`.
- `ExecutionContext` = `{run_id, extras: dict}`. Errors raise
  `BlockExecutionError(ErrorEnvelope)` with structured `{code, message, hint,
  param, given, expected, rationale, node_id, block_id}` — the structured
  fields feed the repair LLM so it disambiguates without parsing English.
- Helper `self.require(params, key, expected=, rationale=)` → structured `PARAM_MISSING`.

Two registries the executors live in: `BUILTIN_EXECUTORS: dict[str, type]`
(`blocks/__init__.py`) and `SIDECAR_NATIVE_BLOCKS: frozenset[str]`
(`executor/real_executor.py`, the in-process fast-path whitelist). Both = 56.

### 5.3 The 56-block catalog
**source (4):** `block_process_history` (pull process events from a source MCP;
nested DF by default), `block_rework_request`, `block_mcp_call` (generic single
MCP call), `block_list_objects` (list master objects).

**transform (20):** `block_filter` (single-condition, path-aware column),
`block_find` (filter+sort+take first/last/all), `block_count_rows`,
`block_mcp_foreach` (call an MCP per upstream row), `block_delta` (adjacent
diff + rising/falling), `block_join`, `block_groupby_agg`, `block_shift_lag`,
`block_rolling_window`, `block_unpivot`, `block_apc_long_form`, `block_union`,
`block_ewma`, `block_histogram` (bins + stats), `block_sort` (multi-col +
top-N), `block_compute` (derived column expression), `block_pluck` (extract
nested field), `block_unnest` (explode array), `block_select` (project/rename).
(`block_spc_long_form` deprecated.)

**logic (8):** `block_threshold` (→ triggered+evidence), `block_consecutive_rule`,
`block_weco_rules` (Western Electric/Nelson SPC rules), `block_cpk`
(Cp/Cpk/Pp/Ppk), `block_any_trigger` (OR + merge evidence), `block_correlation`,
`block_hypothesis_test` (t-test/ANOVA/chi-square), `block_linear_regression` (OLS).

**check (1):** `block_step_check` (aggregate → scalar → pass/fail; Skill-step terminal block).

**output (23):** `block_alert` (the **only** alarm-phase block), `block_data_view`
(table), and **18 dedicated SVG chart blocks**: `block_line_chart` (+control
rules/highlight), `block_bar_chart`, `block_scatter_chart`, `block_box_plot`,
`block_splom` (scatter matrix), `block_histogram_chart` (+USL/LSL/normal fit),
`block_xbar_r` (X̄/R + full WECO R1-R8), `block_imr` (individual+moving range),
`block_ewma_cusum` (small-shift detector), `block_pareto` (+cumulative 80%),
`block_variability_gauge`, `block_parallel_coords`, `block_probability_plot`
(Q-Q + Anderson-Darling), `block_heatmap_dendro`, `block_wafer_heatmap` (IDW
interpolation), `block_defect_stack`, `block_spatial_pareto`,
`block_trend_wafer_maps` (small-multiples). Plus two composite one-line panels:
`block_spc_panel`, `block_apc_panel` (source→chart in one block). (`block_chart`
generic deprecated.)

### 5.4 Pipeline / DAG model
`PipelineJSON = {version, name, metadata, inputs[], nodes[], edges[]}`.
- **Node** = `{id, block_id, block_version:"1.0.0", position:{x,y}, params:{}, display_label?}` (`block_id` = block name).
- **Edge** = `{id, from:{node,port}, to:{node,port}}` (`from` ↔ `from_` in Python).
- **Input** = `{name, type, required, default?, example?, description?}`; referenced in params as `"$name"` (full-string only, no interpolation).

**DAG executor** (`pipeline_builder/executor.py::PipelineExecutor.execute`):
1. resolve inputs (runtime values + declared defaults; canonical fallbacks like tool_id→EQP-01 so preview doesn't red-banner).
2. Kahn topological sort (raise on cycle).
3. per node in topo order: gather `inputs[dest_port]=cache[src_node][src_port]`; any upstream missing/failed → skip fail-fast (`overall_status="failed"`); substitute `$name`; `await executor.execute(...)`; cache by node id; emit `pb_run_start/pb_node_start/pb_node_done/pb_run_done`.
4. build result summary: terminal logic node's `triggered`+evidence, all `chart_spec`s (sorted by `sequence` param then x), data_views, alerts.

**Nested vs flat data:** canonical row type is `list[dict]` with nested values.
`block_process_history` defaults `nested=true`; chart blocks call
`ensure_flat_spc` at entry to auto-flatten. **Path syntax** (`path.py`):
`a.b.c` (dot), `arr[]` (whole array), `arr[].field` (pluck from each). Tokens
must match `[a-zA-Z0-9_]+`; leading-dot/dunder forbidden (read-only).

### 5.5 Validator rules (`pipeline_builder/validator.py`)
Each yields `{rule, message, node_id?, edge_id?}`. C1 schema parse; C2 block
exists in catalog; C3 block status (if enforcing production); C4 port
compatibility (from/to ports declared + types match); C5 no cycle; **C6 param
schema** (required present + shallow type/enum, skips `$`-refs, emits
`PARAM_MISSING`/`PARAM_TYPE_WRONG`/`PARAM_VALUE_INVALID` with a description
snippet as rationale); **C7 endpoints** (≥1 source AND ≥1 output block); C9
chart sequence collision (warn); C10 undeclared `$input` ref; C11-C13 kind
rules (`auto_patrol` needs `block_alert`; `auto_check`/`skill` need a chart and
NO alert); **C14 orphan** (node with zero in+out edges, exempt if
`meta.standalone_capable`); **C15 source-less** (non-source node with outgoing
but no incoming → silent break).

### 5.6 Boot consistency invariant
Adding a block touches **5 places** (executor file, `BUILTIN_EXECUTORS`,
`SIDECAR_NATIVE_BLOCKS`, `seed.py:_blocks()`, `pb_blocks` DB row). At boot
`check_block_consistency()` diffs all four registries and logs drift at ERROR
(does not raise — boots for observability). On no drift it logs
`N builtin, N native, N seed, N DB` — these four must be equal (currently 56).
Excludes `source=mcp_auto` rows.

---

## 6. The agent system (the hard part)

This is the part that turns "一句話" into a runnable pipeline. Read this section
the way you'd read a block doc: each component leads with **what it is and what
it does** (plain language), and only then gives its **inputs / outputs /
mechanics**. If you only read the bold "Purpose" line of each node, you still get
a correct mental model.

### 6.0 The two non-negotiable design rules
1. **Flow control lives in graph nodes; the LLM only does narrow reasoning.**
   Every "what next / which tool" decision is a deterministic node, or a
   classifier node that routes to a fixed downstream sequence — never a rule
   buried in a prompt. (LLMs disobey prompt-flow; prompts aren't unit-testable; a
   node failure points at one node.) Each LLM node does exactly one narrow job —
   classify, extract, or write — never "decide the next step."
2. **No case-specific rules in prompts.** A failing example never earns a new
   prompt rule; it earns a one-line principle, or a check moved into a node /
   schema / structured field. Otherwise the prompt becomes an unmaintainable list
   of cases that a new phrasing bypasses.

There are **two** agents. The **Builder** (§6A) builds pipelines. The **Chat**
agent (§6B) answers ops questions and, when the user wants to build something,
calls the Builder as a sub-agent. §6C covers how their events reach the screen.

Both are LangGraph state machines: a shared `TypedDict` state, nodes that return
only the keys they changed, and conditional edges (router functions) that read
the state and pick the next node.

---

## 6A. The Builder (Glass Box)

### What the Builder does, in one breath
You give it an instruction ("show EQP-08's SPC trend for the last 7 days and
count the OOC events"). It (1) writes a **plan** of intent-only phases, (2) asks
you to confirm the plan, (3) works through the phases one at a time, picking and
wiring blocks while checking its own work after every step, and (4) finalizes a
validated pipeline. It is "Glass Box" because every decision streams to the UI as
it happens.

### The 6 stages (the spine)
| # | Stage (node) | What it does, plainly |
|---|---|---|
| 1 | **goal_plan** | Turn the instruction into 3-7 *intention* phases. No blocks yet — just "what each step should achieve." |
| 2 | **goal_plan_confirm_gate** | Show the plan to the user and wait for "confirm" (or edits). Skipped when chat launched the build. |
| 3 | **task_contract_extractor** | Extract a structured summary of the request (the action, the filters, the output kind, any target count) used later to judge "are we done?". |
| 4 | **agentic_phase_loop** | The ReAct worker. For the current phase, pick a block → add it → wire it → set params, one tool call per round, previewing real output after each change. |
| 5 | **phase_verifier** | After the worker signals "phase done," deterministically check the result and either advance to the next phase or reject with a reason. |
| 6 | **finalize** | Validate the whole pipeline and decide the final status (finished / partial / failed). |

Plus three **escape hatches** that only fire when something goes wrong:
`phase_revise` (the worker is stuck → reflect and retry once), `halt_handover`
(still stuck → ask the user what to do), `judge_clarify_pause` (the data came
back thin → ask the user whether to continue/replan/cancel).

The flow:
```
goal_plan → confirm → task_contract → agentic_phase_loop ⇄ phase_verifier → finalize → END
                                          │ stuck → phase_revise → (retry | halt_handover → ask user)
```

> **One rule that governs the whole loop:** the phase index only moves forward
> inside `phase_verifier` (or a manual "continue" from the judge pause). The
> worker loop never advances it. So "did we finish a phase?" is always a
> deterministic decision, never the LLM's opinion.

---

### 6A.1 goal_plan
**Purpose.** Translate a free-text instruction into a short, ordered list of
*intentions* — "fetch the raw events," "reshape to the one SPC chart," "draw the
trend," "count the OOC." Deliberately **no block names, no column names, no
tool verbs.** Picking blocks is the worker's job (stage 4); mixing the two is
what made earlier versions brittle.

**Input.** the instruction (≤2000 chars) + declared `$inputs` + any existing
canvas nodes + injected planning knowledge.

**Output.** a list of phases + `status="goal_plan_confirm_required"`. Each phase:
```json
{"id":"p1","goal":"<one business sentence>",
 "expected":"raw_data|transform|verdict|chart|table|scalar|alarm",
 "expected_output":{"kind":null,"value_desc":null,"criterion":null},
 "why":null,"user_edited":false}
```
`expected` is the single most important field — it's the phase's "type," and the
verifier later uses it. (3-7 phases; an invalid `expected` coerces to
`transform`.)

**How it works.**
- *Prompt* tells the model: output goal-oriented phases in business language;
  never leak block names / column names / tool verbs; one chart and one verdict
  are separate phases; if the user names a single SPC chart / APC param / nested
  field, include a `transform` phase between raw_data and downstream; don't invent
  phases the user didn't ask for; emit `{"too_vague":true,...}` if the request is
  unworkable. These are *principles*, not a case list.
- *Robustness:* up to 2 attempts. Parsing the JSON successfully always wins (even
  if the provider flagged a transient error). A failure is classified
  `provider_error | empty_output | unparseable` and retried once. All-fail →
  `status="failed"`; `too_vague` → `status="refused"`.
- *Deterministic safety nets (in the node, not the prompt):* if the instruction
  clearly asks for a chart but no phase is `expected=chart`, append one; if it
  focuses on a nested field but there's no transform phase between the source and
  the output, insert one. This is the "principle in a node" pattern that replaces
  prompt case-rules.

### 6A.2 goal_plan_confirm_gate
**Purpose.** Put a human in the loop before any building happens — the user sees
the plan and confirms or edits it. This is the "G" in Glass Box.

**Input/Output.** Pauses the graph with an `interrupt({kind:
"goal_plan_confirm_required", plan_summary, phases})`. The UI shows the plan; the
user resumes with `{confirmed: true}` or `{confirmed:true, phases:[edited...]}` or
`{confirmed:false}`. `false` → `status="refused"`. Edited phases are re-validated
against the `expected` enum.

**Special case.** When the **chat agent** launched this build, it passes
`skip_confirm=true` — the gate auto-confirms (the chat conversation already *was*
the confirmation) and never pauses.

### 6A.3 task_contract_extractor
**Purpose.** Write down, in a structured form, *what success looks like*, so the
verifier can later judge progress without re-reading the prose.

**Input.** the (scrubbed) instruction. **Output.** a `task_contract`:
```
{primary_action, source_filters:{}, data_filters:{}, output_kind,
 markers:[], count_target:int|null, count_strictness:"strict|flexible|none"}
```
(e.g. primary_action="show trend chart", markers=["UCL","LCL","OOC"],
count_target=null). One LLM call; on any failure it returns `null` and the
verifier falls back to a simpler judge. Harmless if it fails.

### 6A.4 agentic_phase_loop — the worker
**Purpose.** This is where blocks actually get added. For the **current phase
only**, the agent runs a ReAct loop: look at the canvas → take one action → see
the result → repeat, until it has built what the phase needs and signals "done."

**Why it's structured the way it is.** A free LLM building a whole DAG drifts and
hallucinates output shapes. So three guardrails are baked in:
1. **One phase at a time** — the agent never sees "build the whole thing," only
   "achieve this one intention."
2. **A sub-phase state machine** (next section) that only exposes the *right*
   tools at the *right* moment, so the agent structurally can't skip steps.
3. **Auto-preview** — after any change to the canvas, the loop runs the node on
   real sample data and feeds the *actual* output columns back to the agent next
   round. This kills "I assumed the output had column X" errors.

**Input (what the agent sees each round).** A single "observation" message built
fresh every round (the agent is stateless between rounds except for a per-phase
message stack). Its sections, in order, are the agent's whole world:
1. completed phases (+ a `data_empty` badge if a prior step returned nothing)
2. the current phase (goal / expected / why)
3. **verifier feedback** — if the last attempt was rejected, *why*, and hints
4. all phases (with a "you are here" marker)
5. available `$inputs`
6. the current canvas nodes + their **real** runtime columns (from auto-preview)
7. connect options (which upstream ports are type-compatible)
8. the last ~6 actions taken this phase (its short-term memory)
9. the user instruction
10. MATCHING BLOCKS (filtered to this phase's `expected`, re-ranked, `[best fit]`)
11. the full block catalog
12. "your next action: one tool call"

**Output (what the agent does).** Exactly one tool call per round (add a node,
connect, set a param, inspect, or signal). The loop dispatches it, auto-previews
if it mutated the canvas, records the action, and loops.

**Budgets / safety.** 32 rounds per phase; a **stuck detector** trips if the
agent repeats the identical action two rounds running (→ hand off to
`phase_revise`). When the agent signals `run_verifier` / `phase_complete` (or a
budget triggers), the loop sets a flag and the router sends control to the
verifier.

### 6A.5 The sub-phase state machine
**Purpose.** Force the agent through the natural order of building one node —
**pick** a block, **construct** it (add + wire), **tune** its params — by only
offering the tools that make sense at each step. This is flow-control-in-a-node:
the agent can't "set a param" before a block exists, because `set_param` isn't on
the menu until the `tune` sub-phase.

**The states and their menus.**
| sub-phase | what the agent is doing | tools it's allowed |
|---|---|---|
| **pick** | choosing which block to use | inspect output, inspect block doc, commit_pick, abort_phase |
| **construct** | adding + wiring the block | add_node, connect, abort_node, inspect_* |
| **tune** | filling in params, then verifying | set_param, run_verifier, abort_node, commit_pick, inspect_* |
| **refine** | (not an LLM step — see below) | — |

**Transitions** are driven by which tool the agent just used:
`pick --commit_pick--> construct`, `construct --connect--> tune`,
`tune --set_param--> tune` (stays), `tune --run_verifier--> tune`, any
`--abort_node--> pick`. An `add_node` that carries its upstream wiring jumps
straight to `tune`. **`refine` is not a state the LLM acts in** — when the
verifier rejects an attempt, *it* sets the next sub-phase directly (a missing
connection → `construct`, a bad param → `tune`, a wrong block → `pick`), so the
agent resumes at exactly the right step.

### 6A.6 phase_verifier
**Purpose.** Be the deterministic referee. After the worker says "phase done,"
decide — by code, not by asking the LLM — whether the phase actually produced
what it should, and either **advance** to the next phase or **reject** with a
concrete reason the worker will see next round.

**Input.** the just-built node + its preview result + the current phase.
**Output.** either advance (write the phase outcome, bump the index, reset the
worker for the next phase) or reject (record the reason; the index does **not**
move; control returns to the worker).

**The checks, in order (first failure rejects):**
1. **Did the block run?** Executor error / validation error → reject "fix params
   or pick a different block."
2. **Is it connected?** A non-source node with no inbound edge is orphaned →
   reject "connect upstream."
3. **Is it a dead end?** A data node with no downstream (once an output node
   exists) is a dangling leaf. This is rejected up to **3 times** (giving the
   agent chances to wire it); on the 4th the verifier **prunes** the dead leaf
   itself and moves on — so a confused agent can't loop forever.
4. **Advance.** With the (default) covers-gate off, advance exactly one phase. (An
   optional strict mode rejects a `chart`/`table`/`scalar`/`alarm` phase that
   ends on a non-presentational block — e.g. a "chart" phase that stops at a
   filter.)

When it rejects, it also picks the sub-phase the worker should resume in (see
6A.5) and writes the rejection reason into the next observation.

### 6A.7 The escape hatches
**phase_revise — "you're stuck, think again."** When the stuck detector or the
round budget trips, this node asks the LLM to diagnose the failure
(`{root_cause, alternative_strategy, can_retry}`). If retryable, it clears the
stuck history, gives the phase half a fresh round budget, and returns to the
worker. Otherwise it escalates to handover. (Only one revise per phase.)

**halt_handover — "I can't; what do you want?"** Pauses and asks the user to pick:
`edit_goal` (rewrite this phase's intent and retry), `take_over` (keep the partial
build), `backlog` (save it for later), or `abort`. When chat launched the build
(`skip_confirm`), it auto-takes-over with a partial result instead of pausing.

**judge_clarify_pause — "the data looks thin; continue?"** When a data source
returns far fewer rows than the target implies, it pauses for
`continue | replan | cancel`. (Wired but currently dormant — the deficit check
moved to runtime.)

### 6A.8 finalize
**Purpose.** Close out the build: run the full validator and decide one honest
status.

**Output status.**
| status | meaning |
|---|---|
| `finished` | all phases done, no structural errors |
| `build_partial` | some phases done (user took over, or ran out) |
| `failed_structural` | the pipeline has structural validator errors |
| `failed` | nothing usable was built |
| `refused` | the request was declined upstream (too vague) |

It emits a `build_finalized` event with the node/edge counts and any warnings, and
(only when `finished`) may do a throwaway dry-run that never changes the status.

### 6A.9 The Builder's tools
The agent drives the canvas through a fixed toolset (this is its entire API):
- **build:** `add_node`, `connect`, `set_param`, `remove_node`, `disconnect`,
  `declare_input`, `rename_node`/`move_node`.
- **look:** `list_blocks`, `explain_block`, `inspect_node_output` (real rows),
  `inspect_block_doc`, `preview`, `get_state`.
- **signal (not blocks):** `commit_pick`, `abort_node`, `abort_phase`,
  `run_verifier`, `phase_complete`.
- **close:** `validate`, `finish` (**gated — `validate()` must pass first**).

Every tool validates before it mutates (ports must match types, params must match
the schema, a column reference must exist in the upstream's *real* output) and
returns a **structured error** (code + hint + the offending field) so the agent
can fix it without parsing English.

---

## 6B. The Chat agent

### What Chat does, in one breath
It answers operations questions in natural language ("why is EQP-07 OOC?", "show
me the last SPC chart"). It figures out what kind of question you asked, fills any
gaps by asking you, calls tools (query data, run a skill, or **build a pipeline**
by handing off to the Builder), and writes a grounded answer — then double-checks
that answer for made-up numbers before showing it.

### The stages
| Stage (node) | What it does, plainly |
|---|---|
| **load_context** | Assemble the system prompt + recent history + a snapshot of current alarms/focus. |
| **intent_classifier(_builder)** | Decide what kind of request this is (a chart? an RCA? a definition? a build instruction?). |
| **intent_completeness** | For a data request, check the user actually specified enough (which tool? what to compute? how to show it?). If not, ask. |
| **llm_call ⇄ tool_execute** | The tool-use loop: the model calls a tool, sees the result, calls another, until it's ready to answer. |
| **synthesis** | Extract the final answer + any chart contract from the model's last message. |
| **self_critique** | Catch hallucinated IDs/numbers and mark or replace them before the user sees them. |

The flow is a classify-then-gate-then-act pipeline: each classifier routes to a
fixed next step, and a single flag (`force_synthesis`) means "stop here and just
render the message" (used by the clarify cards and error paths).

### 6B.1 The classifiers (what kind of question is this?)
**Purpose.** Route deterministically. The model's only job here is to *label* the
request; the graph decides what happens for each label.

- **builder classifier** (runs first, only in builder mode): 7 labels —
  BUILD_NEW, BUILD_MODIFY, EXPLAIN, COMPARE, RECOMMEND, KNOWLEDGE, AMBIGUOUS.
  EXPLAIN/COMPARE/RECOMMEND go to the **Block Advisor**; BUILD_* go toward a build.
- **chat classifier**: 5 labels — `clear_chart`, `clear_rca`, `clear_status`,
  `knowledge`, `vague`. `vague` immediately asks a clarifying question instead of
  guessing. A standalone rule/algorithm name = `knowledge`; the same thing with a
  target ("why is EQP-07 OOC") = `clear_rca`.

**Bypass.** If the message carries an `[intent=...]` or `[intent_confirmed:...]`
prefix (i.e. the user already answered a clarify card), the classifiers step
aside — the decision was already made.

### 6B.2 intent_completeness (don't build on a vague request)
**Purpose.** Stop the agent from guessing. For a clear data request, deterministically
check three dimensions are specified; if any is missing, ask the user with a card
instead of building something wrong.

**The three dimensions.**
- **inputs** — did they name equipment / lot / step / date? (Normalized to canonical
  names like `tool_id`, `time_range`.)
- **logic** — what to compute (OOC rate, count, trend, cpk…)?
- **presentation** — how to show it (line chart / control chart / table / alert…)?
  Users skip this one most, so the check is strict.

**Output.** Complete → proceed. Incomplete → emit a `design_intent_confirm` card
(`{card_id, inputs, logic, presentation, alternatives}`) and stop the turn. The
user picks options and re-sends with an `[intent_confirmed:CARD ...]` prefix.

### 6B.3 The Block Advisor and the dimensional clarifier
**Block Advisor** (for EXPLAIN/COMPARE/RECOMMEND): answers "how do I use this
block / A vs B / which should I use" by **fetching the block's facts from the
database at question time** (never from hardcoded prompt text) and writing a
focused answer.

**Dimensional clarifier** (used before a build): a set of deterministic detectors
for the *specific* ambiguities that bite pipeline builds — e.g. "you named one
tool but said '各機台'" (one machine or all?), "OOC but which family — APC/SPC/FDC?",
"bar chart but along what axis?", "trend but at what time grain?". It detects the
ambiguity by code and uses the LLM only to phrase the question in the user's
language. The user's answer is spliced back into the build goal deterministically.

### 6B.4 The tool-use loop (llm_call + tool_execute)
**Purpose.** Let the model act: call a tool, read the result, decide the next
call, up to 25 iterations, then answer.

**llm_call** is the model turn. It sees only the tools its role is allowed
(ON_DUTY users, for instance, can't see `build_pipeline_live` or any draft/build
tool — the gate is fail-closed: unknown role = most restricted). It retries once
on a transient provider blip and, if the provider keeps failing, returns a clean
"the call failed" answer instead of crashing.

**tool_execute** runs the tool. Most tools are a straight dispatch, but two are
special:
- **confirm_pipeline_intent** — "write down what I'm about to build and wait for
  the user's OK" (emits a confirm card, stops the turn).
- **build_pipeline_live** — hand off to the Builder. Before doing so it **cleans
  the request** so the Builder gets a parametric intent, not stray specifics:
  it strips literal IDs that conflict with declared `$inputs`, strips any block
  names the chat model guessed, and rewrites "全廠/各機台" back to "the `$tool_id`
  machine" so the build doesn't silently expand scope. Then it streams the
  Builder's events to the chat surface and, if a pipeline came out, **auto-runs
  it** and streams the result.

### 6B.5 synthesis + self_critique (answer, then fact-check the answer)
**synthesis** pulls the final text and any chart contract out of the model's last
message. (House rule: a chart that was already rendered live is never re-embedded
in the contract — the live render is the source of truth.)

**self_critique** is the trust layer. First, a free deterministic scan: any ID in
the answer (`LOT-…`, `EQP-…`, `APC-…`) that doesn't appear in any tool result is
flagged as fabricated and marked `⚠️[捏造]`. Then one quick LLM pass checks that
every concrete number (readings, timestamps, control limits, %) is traceable to a
tool result, replacing unsourced numbers with `[查無資料]`. This is what stops the
agent from confidently citing data it never fetched.

---

## 6C. How agent activity reaches the screen (events + protocols)

### 6C.1 The two surfaces speak different event dialects
The Builder emits rich internal events (`goal_plan_proposed`, `phase_action`,
`phase_completed`, `build_finalized`, plus pause events). The **chat surface**
only understands a small `pb_glass_*` vocabulary: `pb_glass_start`,
`pb_glass_op` (one canvas operation), `pb_glass_chat` (a narration line),
`pb_glass_done` (carries the finished `pipeline_json`), then `pb_run_start` /
`pb_run_done` (carries the result) for the auto-run.

A single bridge function translates Builder events → `pb_glass_*`. **Its one
hard rule:** pass the **raw structured arguments** through (the block name, the
params, the from/to ports), never a flattened text summary — because the frontend
rebuilds the live canvas from those structured fields. Flattening them once made
the live canvas go blank; the rule exists to prevent that regression.

### 6C.2 Two different "confirm" handshakes (don't conflate them)
- **Intent confirm** (the `design_intent_confirm` card → `[intent_confirmed:CARD]`
  re-POST): used *before* a build, when the request is ambiguous. The card lists
  the dimensions to pin down; the user picks and re-sends the same message with an
  `[intent_confirmed:<id> dim=val ...]` prefix on the **same chat session**.
- **Build-pause resume** (`/chat/intent-respond`): used to *un-pause* a build that
  already started and hit a handover/judge interrupt. Keyed to the chat session
  via a pending-record so the right paused build resumes.

The chat-session-id vs build-session-id distinction is load-bearing: pause cards
carry the **chat** session (what the card posts back to) and the **build** uuid
(for trace correlation) separately.

### 6C.3 The LLM client (one switch for the whole platform)
A single client wraps every provider. `LLM_PROVIDER` selects Anthropic-native or
any OpenAI-compatible endpoint (OpenRouter/vLLM — the production path, KIMI K2.5
by default, pinned to Fireworks so prompt-cache survives). Every caller goes
through one `create(system, messages, max_tokens, tools)` that returns a normalized
response. Two fields matter for debugging: `stop_reason` (normalized) and
`finish_reason` (the **raw** provider value — it's how you tell a real
provider-error apart from a JSON-parse bug). The client itself never retries —
retry policy lives in the callers that know what "a good answer" looks like.
**To change the model, you change one `.env` line** (`OLLAMA_MODEL` +
`LLM_PROVIDER`).

### 6C.4 Build traces (how you debug the agent)
Every build writes one JSON file (`/tmp/builder-traces/*.json`) recording the
plan, every LLM call (the prompt it saw + its raw response + finish_reason), every
graph step, and every verifier verdict. A summary renderer turns that into a
readable "plan → which phase got stuck → round-by-round history" (the same view
powers the admin Build-Traces tab). A replay tool can re-run a single saved LLM
call under tweaks to answer "would changing X have changed the agent's choice?"
without guessing.
---

## 7. System MCP (external data sources)

### 7.1 Definition + execution
`mcp_definitions` row (§3.1) holds `api_config={endpoint_url, method, headers}` +
`input_schema`. Sidecar block `block_mcp_call` (`McpCallBlockExecutor`):
`require(mcp_name)` + `args` dict → `JavaAPIClient.get_mcp_by_name` → parse
`api_config` (malformed/missing endpoint/method∉{GET,POST} →
`INVALID_MCP_CONFIG`) → httpx dispatch (30s; GET args→query, POST args→JSON
body) → `_flatten_response` normalizes (list | dict keys
events/dataset/items/data/records/rows) → DataFrame on `data` port. Error codes
`MCP_HTTP_ERROR`/`MCP_UNREACHABLE`/`MCP_LOOKUP_FAILED`/`MCP_NOT_FOUND`.

### 7.2 ${ENV} header interpolation (POC feature)
The POC adds an admin **headers form** on `/admin/system-mcps` and a runtime
helper `pipeline_builder/blocks/_http_helpers.py::resolve_headers(headers, *,
mcp_name)` — `${NAME}` regex substitution from `os.environ`, raising
`BlockExecutionError(INVALID_MCP_CONFIG)` naming any missing env vars. Secrets
are **never stored in DB**; the header value is `${EXTERNAL_API_TOKEN}` and the
real value lives in `python_ai_sidecar/.env`. `block_mcp_call` + `block_mcp_proxy`
call `resolve_headers` instead of reading headers verbatim.
*(On `main` this helper does not exist — headers pass through verbatim. It is a
POC-branch addition. Implement the POC behavior.)*

### 7.3 V54 derivative blocks/skills
When an admin checks `produces_block`/`produces_skill`, Java atomically writes:
`mcp_definitions.produces_*` = true; a `pb_blocks` row (`source='mcp_auto'`,
`source_mcp_id`, `implementation={type:"mcp_proxy", mcp_name, delegate_block:
"block_mcp_call"}`); a single-block `pb_pipelines` DAG; a `pb_published_skills`
row (`source='mcp_auto'`). At runtime the registry sees
`implementation.type=="mcp_proxy"` and binds `McpProxyBlockExecutor(mcp_name)`
instead of a `BUILTIN_EXECUTORS` lookup; that executor exposes friendly per-MCP
params and passes all non-underscore keys as `args`.

The generator (`mcp_derivative/generator.py`) drafts the block + skill with
**Haiku** (`MCP_DERIVATIVE_LLM_MODEL` default `claude-haiku-4-5-20251001`,
hardcoded cheap; `PROMPT_VERSION` bumped on prompt change for audit). A
deterministic pre-LLM lint gate (`MIN_DESCRIPTION_CHARS=200` error / `400` warn)
blocks generation on too-thin descriptions before burning tokens. The system
prompt is **principles-only** (no case rules). LLM output is **always a draft** —
the admin reviews/edits in the form before commit; MCP description changes do
NOT auto-regenerate (UI shows a stale warning).

### 7.4 Single-source-of-truth rule
LLM prompts never hardcode MCP usage. The `query_data`/`execute_mcp` tool
descriptions tell the LLM to pick `data_source` from a `<mcp_catalog>` injected
at runtime from `name + description + input_schema`. If an MCP changes behavior
but a prompt's hardcoded usage doesn't, the LLM generates wrong code — so the DB
description is the only allowed source.

---

## 8. Knowledge layer

`agent_knowledge` (RAG) + `block_docs` (block-level). Two-layer injection
(`agent_builder/graph_build/nodes/_knowledge_inject.py::build_knowledge_hint`):
- **Layer 1 (always-on):** `list_high_priority_knowledge` (global `priority='high'`,
  **no embedding** so first-principle rules always reach the LLM regardless of
  multilingual recall) → "## Domain first principles".
- **Layer 2 (RAG):** cosine search filtered by `applies_to` layer.

Call sites: **goal_plan** injects `layer="plan"` (planning hints); **the pick
sub-phase of agentic_phase_loop** injects `layer="execute"` (block-choice rules,
e.g. "全廠 → list_objects + foreach" reaches the layer that actually picks the
source block). Prod state: execute injection ON, layered-plan OFF.

`block_docs.markdown` (frontmatter + body) is the single source of truth for
`list_blocks` (frontmatter `description:` → catalog head) and
`explain_block`/`inspect_block_doc` (body). Sidecar caches 60s, falls back to
`pb_blocks.description` for unmigrated blocks.

---

## 9. Config & feature flags

`config.py` (`SidecarConfig` frozen dataclass, `from_env()`): `service_token`,
`port=8050`, `java_api_url`, `java_internal_token`, `java_timeout_sec=30`.
`feature_flags.py`: env `ENABLE_*` flags with a per-request `X-Feature-Flags`
header override (ContextVar). Key flags: `prompt_cache` (default ON),
`auto_signal`, `atomic_add_connect`, `strict_tool_id`, `plan_knowledge`,
`execute_knowledge`, `layered_plan_knowledge`, `goal_aware_matching`,
`rich_schema_values`, `orphan_resolve`, `presentation_lookahead`,
`next_memo`. **Caveat:** the header override is a no-op for SSE build/chat
streaming (middleware resets before the stream) — use env + restart for A/B.

---

## 10. Frontend

Next.js App Router, standalone, inline styles, NextAuth v5.

### 10.1 Pages (POC-relevant)
`/` → `/dashboard`; `/login` (enumerates registered OIDC providers + local
form); `/skills` (Library landing — published-skill catalog, search/filter);
`/skills/[slug]` (run); `/skills/[slug]/edit` (author — triggers/steps + launch
builder embed); `/skills/new`; `/chat/new` + `/chat/[sessionId]` (persistent
conversation unifying AI Agent + builder canvas + results); `/agent-knowledge`
(directives/RAG/lexicon/examples authoring); `/admin/pipeline-builder/[id]`
(canvas edit — Glass Box build target); `/admin/pipeline-builder/new` (3-step
wizard kind→trigger→inputs); `/admin/block-docs` (+ `/[block_id]/[version]`
editor); `/admin/build-traces` (trace viewer); `/admin/system-mcps` (MCP admin
form + headers + produces toggles); `/admin/users` (role mgmt); `/help/charts`
(+ `/[type]` — 18 chart catalog + live editor); `/me/profile`,
`/me/change-password`. (Peripheral/L4: `/alarms`, `/rules`, `/topology`,
`/system/*` — out of POC scope.)

### 10.2 API proxy contract (`/api/*`)
Every backend call is a proxy. Upstream env: `FASTAPI_BASE_URL` (Java :8002),
`SIDECAR_BASE_URL` (:8050). Auth via `lib/auth-proxy.ts` (`authHeaders()` →
user JWT, falls back to `INTERNAL_API_TOKEN`); sidecar routes use
`X-Service-Token`. Map: `/api/agent/*` → Java `/api/v1/agent/*` (SSE bridged);
`/api/pipeline-builder/*` → Java (reads `/pipeline-builder/*`, writes
`/pipelines/*`); `/api/skill-documents/*`, `/api/block-docs/*`,
`/api/agent-knowledge/*`, `/api/mcp-*` → Java; `/api/admin/build-traces*` →
**sidecar** `/internal/agent/build/traces*`; `/api/auth/[...nextauth]` →
NextAuth.

### 10.3 Pipeline Builder UI
Composition root `BuilderLayout` wraps a `BuilderProvider` (reducer holding draft
`pipeline_json`, selection, 50-deep undo/redo, status/kind meta). Canvas =
React Flow (`DagCanvas` + `CustomNode` + `DeletableEdge`, Dagre LR auto-layout).
Left palette `BlockLibrary` (by category, opens `BlockDocsDrawer`). Config via
`NodeInspector` → `SchemaForm` (JSON-schema widgets: enum→select,
`x-column-source`→column picker, `x-suggestions`→datalist). Right rail = Agent |
Parameters | Runs. Glass Box live-build = `AgentBuilderPanelV30` (renders
`GoalPlanCard` confirm, `PhaseTimeline`, `HandoverModal`); SSE op events
translated to canvas mutations by `lib/pipeline-builder/glass-ops.ts`. Chat-driven
read-only mirror = `LiteCanvasOverlay` (Canvas / 結果 tabs, auto-flips to
Results on run done). Results = `PipelineResultsPanel` (alert banner + evidence
table + chart list) + `ChartRenderer` (18 SVG chart components).

### 10.4 Auth + shell
NextAuth v5 multi-provider (Azure AD / Google / Keycloak / Okta, each registers
only when its `OIDC_*` env present) + always-on Credentials. Credentials →
Java `/auth/login`; OIDC → `signIn` callback → Java `/auth/oidc-upsert`
(shared secret) → Java JWT stashed on the session. Middleware gates non-public
paths when `AIOPS_AUTH_REQUIRED=1` and redirects on inner-JWT expiry.
`AppShell` = Topbar + collapsible left `ContextualSidebar` (role-based nav:
Operations all-roles / Knowledge Studio PE+IT_ADMIN / Admin IT_ADMIN-only) +
right AI Agent rail + Lite Canvas overlay.

### 10.5 Shared output contract (`aiops-contract`)
Dual-language (TS `report.ts` + Python pydantic `report.py`).
`AIOpsReportContract` = canonical Agent/Skill output: `$schema`
("aiops-report/v1"), `summary`, `evidence_chain[]`, `visualization[]` (legacy),
`suggested_actions[]` (AgentAction | HandoffAction discriminated union),
`findings`, modern `charts[]` (ChartDSL: type/title/data/x/y/rules/highlight).
Frontend `ContractRenderer` dispatches to a viz registry.

---

## 11. Build/deploy & smoke

systemd units: aiops-app (8000), aiops-java-api (8002), aiops-python-sidecar
(8050). `deploy/update.sh` = frontend; `deploy/java-update.sh` = Java + sidecar
(rebuild jar + venv, apply canonical block seed, restart both). Frontend
standalone needs static+public copied into `.next/standalone`. New `V*.sql`
applied via manual `psql` (Flyway disabled in prod).

Quality gates that must pass: **SLASH-17** (17 builder commands graded against
golden plans, ~17/17), a chat-mode eval (confirm → build → run yields a
pipeline + result), the block-consistency boot invariant (4 registries = 56),
and pure-Mockito Java unit tests.

---

## 12. Suggested rebuild order (for the implementing team/agent)

Build the substrate before the agent; the agent is only as reliable as the
blocks and the executor beneath it.

1. **DB + Java skeleton** — entities (§3), the two security chains + roles (§4.4), `ApiResponse`/`JsonUtils`/`SseEmitterBridge` helpers, block + pipeline + MCP CRUD (`/internal/*` + `/api/v1/*`).
2. **Block executor engine** (§5) — the `BlockExecutor` ABC, the DAG executor, the path syntax, the validator, the boot invariant. Implement 5-10 core blocks first (process_history/mcp_call, filter, groupby_agg, threshold, line_chart, data_view) and the test harness. Then fill out to 56.
3. **System MCP** (§7) — definition CRUD, `block_mcp_call` + `${ENV}` headers, then V54 derivatives.
4. **LLM client** (§6.7) — provider switch, retry, finish_reason, prompt cache.
5. **Builder graph** (§6.3) — goal_plan → confirm → agentic_phase_loop (sub-phase machine) → phase_verifier → finalize, the builder toolset (§6.4), BuildTracer (§6.8). Stand up SLASH-17 as the regression gate from day one.
6. **Chat orchestrator** (§6.2) — load_context → classifiers → completeness gate → llm_call/tool_execute → synthesis; role-gated tools; the `build_pipeline_live` bridge into the builder graph.
7. **Knowledge layer** (§8) — agent_knowledge + block_docs + two-layer injection.
8. **Frontend** (§10) — auth/shell, Library, Builder canvas + Glass Box, Try-Run results, Block Docs, Build Traces, System MCP admin.

Throughout, hold the two hard rules: flow control in graph nodes (not prompts),
and block `description`/`param_schema`/`examples` as the single source of truth.

---

*End of technical build specification.*
