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

## 6. The agent system (the hard part) — deep dive

Two LangGraph stacks share one LLM client and reach state only through Java.
**Builder Glass Box** (`agent_builder/graph_build/`) constructs pipelines;
**Chat orchestrator** (`agent_orchestrator_v2/`) answers ops questions and, on a
pipeline-build intent, drives the builder graph as a sub-agent. This section is
implementation-grade: routers are reproduced as predicate logic, with the state
keys each reads.

### 6.1 The two non-negotiable design rules
1. **Flow control lives in graph nodes; the LLM only does narrow reasoning.**
   Every "what next / which tool" decision is a deterministic node or a
   classifier node routing to a fixed downstream sequence — never a prompt rule.
   LLMs disobey prompt-flow (proven repeatedly), prompt-flow isn't unit-testable,
   and a node failure points at a specific node. Each LLM node does one narrow
   job (classify / extract / write), never "decide the next step."
2. **No case-specific rules in prompts.** A failing trace never earns a new
   prompt rule ("ban mean/std for box_plot"); every such rule is bypassed by a
   new phrasing in months. Abstract to a one-line principle, or move the check to
   a graph node / schema / structured-meta field.

Both stacks: `GraphState`/`BuildGraphState` are `TypedDict`s; LangGraph merges
returned keys (last-write-wins, except list-append reducers and the `add_messages`
message reducer). A boot assert fails import if any `run()` kwarg isn't a declared
state key (LangGraph silently drops undeclared keys).

---

## 6A. Builder Glass Box graph (v30 ReAct)

Compiled once, cached in a module global; checkpointer is an in-process
`MemorySaver` (restart drops paused sessions). v30 is the default path
(`v30_mode=True`); a legacy v27 macro-plan path coexists behind `AGENT_BUILD_V30=0`.

### 6A.1 Node wiring & routers
Linear spine then a verify loop:
```
START ─_route_entry→ goal_plan ─_route_after_goal_plan→ goal_plan_confirm_gate[interrupt]
  ─_route_after_goal_plan_confirm→ task_contract_extractor → resolve_presentation_contracts
  → agentic_phase_loop ⇄ phase_verifier → finalize → inspect_execution → layout → END
escape hatches: phase_revise, halt_handover[interrupt], judge_clarify_pause[interrupt], step_pause_gate[interrupt]
```
Every conditional edge, as predicate logic (the `status`/flag keys are the
contract — reproduce exactly):

| Router | Predicate | → node |
|---|---|---|
| `_route_entry` | `v30_mode` | goal_plan; else clarify_intent (v27) |
| `_route_after_goal_plan` | `status ∈ {refused,failed}` → finalize | else goal_plan_confirm_gate |
| `_route_after_goal_plan_confirm` | `status=="refused"` → finalize | else label `"agentic_phase_loop"` **remapped to `task_contract_extractor`** (easy to miss) |
| `_route_after_phase_loop` | `status=="phase_revise_pending"` → phase_revise; `v30_verify_now` → phase_verifier | else **self-loop** agentic_phase_loop (keep building chain in same phase) |
| `_route_after_phase_verifier` | `v30_judge_pause` → judge_clarify_pause; `idx>=len(phases)` → finalize; `debug_step_mode` → step_pause_gate | else agentic_phase_loop |
| `_route_after_phase_revise` | `status=="handover_pending"` → halt_handover | else agentic_phase_loop |
| `_route_after_handover` | `status=="phase_in_progress"` → agentic_phase_loop | else finalize |
| `_route_after_judge_clarify` | `replan_pending`→goal_plan; `cancelled`→halt_handover; `finished`→finalize | else agentic_phase_loop |
| `_route_after_inspect` | v30 (`v30_phases` set) → **always** layout→END | (v27 may go reflect_plan→validate) |

Two non-obvious facts: (a) the confirm router's label is remapped to the
contract extractor, not the loop; (b) **phase index advancement is owned solely
by `phase_verifier` (auto) and `judge_clarify_pause` (manual continue)** — the
loop node never advances `v30_current_phase_idx`. `v30_judge_pause` is wired but
**dormant** in the current build-time verifier (data-deficit detection moved to
runtime), so the judge path is reachable only if another path sets the flag.

### 6A.2 `goal_plan` node
Emits 3–7 **intent-only** phases (`MAX_PHASES=7`, `MIN_PHASES=1`), no block
selection. Phase output schema (each phase, post-parse):
```json
{"id":"p1","goal":"<one-sentence business intent>",
 "expected":"raw_data|transform|verdict|chart|table|scalar|alarm",
 "expected_output":{"kind":str|null,"value_desc":str|null,"criterion":str|null},
 "why":str|null,"user_edited":false}
```
Invalid `expected` → coerced to `"transform"`. Top-level: `plan_summary`,
`phases[]`, optional `alarm`.

**System prompt skeleton** (hard rules, abbreviated — do NOT copy as case rules,
these are principles):
- Role = pipeline architect; output goal-oriented phases; MUST NOT name blocks.
- Plan layer is **intention only** — forbidden to leak (a) block names, (b)
  data-structure / column names, (c) tool-bound verbs (unnest/sort/groupby). Use
  business language. `value_desc` = one business sentence, no columns/counts/
  enumerations.
- Linear order, no `depends_on`. One chart + one verdict = **separate** phases.
- Phase atomicity: each phase ≈ 1–2 blocks; chart blocks self-compute their
  stats (don't pre-add a stats-transform phase for them).
- Transform-phase necessity: if the user names a single SPC chart / APC param /
  nested field, the plan MUST include a `transform` phase between `raw_data` and
  downstream.
- Don't invent phases the user didn't ask for (no auto summary/scalar/verdict).
- Escape hatch: `{"too_vague":true,"reason":"..."}`.

**Bounded retry** (`_MAX_PLAN_ATTEMPTS=2`): `_attempt_plan_parse(resp)` returns
`(decision, fail_kind)`. Parse success **always wins** (even if the provider
flagged an error). Else `fail_kind ∈ {provider_error (stop_reason=='error'),
empty_output, unparseable}` triggers one retry. Terminal: all-fail →
`status="failed"`; `too_vague` → `status="refused"`; `<MIN_PHASES` →
`status="failed"`; success → seeds v30 state (`v30_current_phase_idx=0`,
`v30_phase_round=0`, empty outcomes) + `status="goal_plan_confirm_required"`.

**Knowledge injection** (gated `ENABLE_PLAN_KNOWLEDGE`): `build_knowledge_hint(...,
layer="plan")` (V58 layered → `applies_to∈{plan,both}` + always-on core + RAG).
Best-effort, never raises.

**Deterministic post-processing** (graph node, not prompt): `_maybe_inject_chart_phase`
(instruction matches chart keywords + no chart phase → append one) and
`_maybe_inject_transform_phase` (nested-focus keywords + raw_data anchor +
downstream output phase + no transform → insert transform after raw_data). These
are the "principle in a node" pattern replacing prompt case-rules.

**`goal_plan_confirm_gate`**: `skip_confirm=True` (chat-launched) auto-confirms,
emits `goal_plan_confirmed(auto)`, no interrupt. Else
`interrupt({kind:"goal_plan_confirm_required", plan_summary, phases})`; resume
`{confirmed:bool, phases?:[...]}`. `confirmed=False` → `status="refused"`; edited
phases re-validated against the `expected` enum with edit-history tracking.

### 6A.3 `task_contract_extractor`
One LLM call after confirm → `v30_task_contract`:
```
{user_instruction, primary_action, source_filters:{}, data_filters:{},
 output_kind, markers:[], count_target:int|null,
 count_strictness:"strict"|"flexible"|"none"}
```
Every key `setdefault`-filled. Skips if already cached / not v30 / no instruction.
Any failure → `v30_task_contract=None` (downstream verifier falls back to a
legacy judge). `max_tokens=600`.

### 6A.4 `agentic_phase_loop` — anatomy of one ReAct round
Budgets: `MAX_REACT_ROUNDS=32` (per phase), `MAX_INSPECT_CALLS_PER_ROUND=5`,
`STUCK_DETECTOR_WINDOW=2`. One tool call per round. Each round = one fresh LLM
call (stateless across rounds except the per-phase message stack
`v30_phase_messages[pid]`, capped to last 32).

**Observation message** the LLM sees each round (section order is the contract):
1. COMPLETED PHASES (prior outcomes: target + advanced_by node/block + `data_empty` badge)
2. CURRENT PHASE (id/goal/expected/why)
3. presentation-contract hint (if resolved)
4. **VERIFIER FEEDBACK** (`v30_last_verifier_reject`: rejected block, covers,
   expected, reason, `missing_for_phase` hints, `would_have_passed_with`)
5. ALL PHASES CONTEXT (`<-- you are here`)
6. AVAILABLE INPUTS (declared `$name`)
7. canvas nodes + runtime schema (from `exec_trace[*].runtime_schema_md`)
8. CONNECT OPTIONS (type-compatible source ports per unfilled input)
9. ACTIONS THIS PHASE (last-6 actions + result digests — memory across rounds)
10. USER INSTRUCTION[:600]
11. MATCHING BLOCKS (covers-filtered, goal-reranked, `[best fit]` tags)
12. AVAILABLE BLOCKS (full two-tier catalog)
13. YOUR NEXT ACTION (single tool call)

Follow-up rounds append `assistant(tool_use)` (filtered to the exact dispatched
tool_use_id — Anthropic requires one result per use) + `user([tool_result,
canvas_diff_md])`, where the diff leads with `▶ YOUR PLAN` (next-memo), then
verifier feedback, then rich sub-phase context, then connect options.

**Auto-preview**: after a mutating tool (`add_node/set_param/connect/remove_node`)
with no error → `preview(node_id, sample_size=5)`; the snapshot (cols[:20],
sample, `runtime_schema_md`, coalesced error) is written to `exec_trace[lid]` so
the next round sees real output shape (defeats output-shape hallucination).

**Stuck detector**: `args_hash = md5(sorted_json(tool,args))[:12]`; the same
`(tool,args_hash)` appearing `STUCK_DETECTOR_WINDOW(2)` rounds in a row →
`status="phase_revise_pending"`, emit `phase_revise_started(reason=
"stuck_repeat_action")`. Hitting `MAX_REACT_ROUNDS` → same with
`reason="max_rounds_no_progress"`.

**`v30_verify_now`** is set when the tool is `run_verifier`/`phase_complete`
(explicit) or `_should_auto_verify` passes (gated; only when a just-added terminal
block's `covers_output` includes `phase.expected` and the agent was "decisive").
For tool-lax providers (KIMI), text matching a "phase done" intent regex
synthesizes a `phase_complete` call.

### 6A.5 Sub-phase state machine
`v30_subphase ∈ {pick, construct, tune, refine}` gates the available toolset per
sub-phase, so the agent structurally cannot skip steps. `_TOOLS_BY_SUBPHASE`:

| sub-phase | exposed tools |
|---|---|
| pick | inspect_node_output, inspect_block_doc, commit_pick, abort_phase (+add_node if auto_signal) |
| construct | add_node, connect, abort_node, abort_phase, inspect_* |
| tune | set_param, run_verifier, abort_node, abort_phase, commit_pick, inspect_* |
| refine | (not an LLM state — deterministic router) |

Transitions (`_next_subphase(current, tool)`):
```
pick:     commit_pick→construct   add_node→construct   abort_phase→refine
construct:add_node→construct      connect→tune         abort_node→pick   abort_phase→refine
tune:     set_param→tune(stay)    run_verifier→tune    abort_node→pick   commit_pick/add_node→construct   abort_phase→refine
```
Atomic `add_node(upstream=...)` from pick/construct/tune lands directly in `tune`
(connect already done in the same call). On transition, `v30_subphase_round`
resets to 0; else increments. **`refine` is a pseudo-state**: only `abort_phase`
yields it (→ surfaces as `phase_revise_pending`); the verifier sets the concrete
next sub-phase (pick/construct/tune) directly on each reject.

### 6A.6 `phase_verifier` decision tree
Constants: `MAX_FAST_FORWARD_CHAIN=4`, `LEAF_PRUNE_AFTER=3`,
`_STRICT_VERIFY_KINDS={chart,table,scalar,alarm}`. Covers gate flag
`BUILDER_VERIFIER_COVERS_GATE` default **OFF**. Branches in order:
1. **no `v30_last_mutated_logical_id`** → `{}` (inspect/no-op round, nothing to verify).
2. **(B) executor failure**: no block_id OR snapshot status ∈ {validation_error,
   failed, error} → `_emit_reject(result=status, missing_for_phase=["fix params
   or pick a different block"])`.
3. **(C) orphan** `_check_orphan` (skip source / `meta.standalone_capable`): target
   has 0 inbound edges → reject (`missing_for_phase=["connect upstream → …"]`).
4. **(C2) non-output leaf** `_nonoutput_leaves` (fires only once an output-category
   node exists): bounded reject up to `LEAF_PRUNE_AFTER(3)` times
   (`v30_leaf_reject_count`), then **`_prune_nodes`** removes the dangling leaf +
   touching edges and falls through to advance (writes `final_pipeline`).
5. **(A) advance**: covers gate OFF → advance exactly ONE phase; if
   `ENABLE_STRICT_PHASE_VERIFY` and `expected ∈ _STRICT_VERIFY_KINDS` and
   `expected ∉ covers_output` → reject (`would_have_passed_with=...`, catches a
   chart phase ending on `block_filter`). Covers gate ON → fast-forward up to 4
   phases whose `expected ∈ covers_internal`.
6. **advance bookkeeping**: per advanced phase write
   `v30_phase_outcomes[id]={status:"completed",advanced_by_block/node,plan_target}`;
   `new_idx=idx+len(advanced)`; reset `v30_phase_round=0`, `v30_subphase="pick"`,
   `v30_pending_*=None`, `v30_leaf_reject_count=0`, clear verifier-reject; emit
   `phase_completed`. The done→finalize decision is the router's (`idx>=len(phases)`).

`_emit_reject` writes `v30_last_verifier_reject` (consumed by next observation),
sets the deterministic next `v30_subphase` (orphan→construct, validation→tune/pick,
else pick), does NOT advance the index → router returns to the loop. Covers
resolved via `produces.covers_output`/`covers_internal`, falling back to legacy
`covers` then an inference table (source→raw_data, chart→chart, data_view→table,
alert→alarm, step_check/threshold→[verdict,scalar], dataframe→transform).

### 6A.7 Interrupt nodes (payloads + resume + routing)
- **`phase_revise`** (LLM self-reflect, not an interrupt; `MAX_REVISE_ATTEMPTS_PER_PHASE=1`):
  asks `{root_cause, alternative_strategy, missing_capabilities[], can_retry}`.
  `can_retry=True` → clear stuck history, halve the round budget
  (`v30_phase_round=16`), `status="phase_in_progress"` → loop. Else / 2nd attempt
  → `status="handover_pending"` with `v30_handover={failed_phase_id, reason,
  missing_capabilities, options_offered:[edit_goal,take_over,backlog,abort]}`.
- **`halt_handover`** (`interrupt`): `skip_confirm` auto-`take_over`→`build_partial`.
  Resume `{choice, new_goal?}`. edit_goal+new_goal → rewrite the phase goal, reset
  round, `phase_in_progress`→loop. take_over/backlog → `build_partial`. abort →
  `failed`, `final_pipeline=None`.
- **`judge_clarify_pause`** (`interrupt`; `MAX_JUDGE_REPLAN=1`): resume
  `{action ∈ continue|replan|cancel}`. cancel → handover/abort. replan → wipe
  phases, set `v30_replan_hint`, `status="replan_pending"`→goal_plan. continue →
  manually advance the index (the verifier cleared its block context on pause).
- **`step_pause_gate`** (`interrupt`, debug only): resume `{action:continue|abort}`.

### 6A.8 `finalize` / `inspect_execution` — status values
`finalize` runs `PipelineValidator`, splits issues into `_STRUCTURAL_RULES
={C6_PARAM_SCHEMA, C14_ORPHAN_NODE, C15_SOURCE_LESS_NODE, C4_PORT_COMPAT,
C16_PLACEHOLDER_LEAK}` vs advisory, then:
```
status = "refused"          if incoming refused
       = "failed"           if v30 and 0 nodes
       = "failed_structural" if structural issues
       = "finished"         if all phases done (idx >= len(phases))
       = "build_partial"    if some phases done (idx > 0)
       = "failed"           otherwise
```
Optional strict deliverable gate (`ENABLE_STRICT_PHASE_OUTPUT`, default OFF):
`finished` + final phase `expected ∈ {chart,table,scalar,alarm}` + no terminal
covers it → `failed_missing_output`. Emits `build_finalized(ok=status=="finished",
counts, warnings, structural_errors)`; an optional dry-run runs only when
`finished` and never changes status. `inspect_execution` derives
`inspection_issues` (DATA_EMPTY / DATA_SHAPE_WRONG / single_point_chart) but on
the v30 path is informational only (router always goes layout→END).

### 6A.9 Builder toolset (`agent_builder/tools.py`)
`list_blocks(category?)`, `explain_block(name)`, `add_node(block_name, version,
position?, params?, upstream?)` (auto-offset, schema-aware param coercion, rejects
undeclared `$refs`, optional atomic add+connect), `remove_node`, `connect(from,
to, from_port="data", to_port="data")` (port-type validated, dedup), `disconnect`,
`set_param(node_id, key, value)` (validates key/enum/`$ref` + `_check_column_in_upstream`
against the computed upstream schema), `declare_input`, `move_node`/`rename_node`,
`update_plan`, `get_state`, `preview(node_id, sample_size)`,
`inspect_node_output(node_id, n_rows≤3)`, `inspect_block_doc(block_id, section)`,
`commit_pick`/`abort_node`/`abort_phase`/`run_verifier`/`phase_complete` (control
signals, not blocks), `validate`, `finish(summary)` (**GATED: `validate()` must
pass first** else `FINISH_BLOCKED`). Errors raise `ToolError` carrying a
structured `ErrorEnvelope` for the repair LLM.

---

## 6B. Chat orchestrator graph (`agent_orchestrator_v2/`)

`GraphState` reducers: last-write-wins except `tools_used`/`render_cards`
(append) and `messages` (`add_messages` dedup-by-id). `MAX_ITERATIONS=25`,
`mode` default `"chat"`.

### 6B.1 Node wiring & routers
Entry `load_context → intent_classifier_builder`. Static edges:
`advisor_dispatch→synthesis`, `synthesis→self_critique`, `self_critique→END`.
Conditional routers (predicate → node):

| Router | Predicate | → node |
|---|---|---|
| `_route_after_builder` (reads `intent`) | builder_{explain,compare,recommend,ambiguous}→advisor_dispatch; builder_{build_new,build_modify}→pre_clarify_check; builder_knowledge→llm_call | else (not builder) → intent_classifier |
| `_route_after_pre_clarify` | `force_synthesis`→synthesis | else llm_call |
| `_route_after_intent` | `force_synthesis or intent=="vague"`→synthesis; builder_*advisor→advisor_dispatch; builder_build_*/knowledge→llm_call; `intent.startswith("clear_")`→intent_completeness | else llm_call |
| `_route_after_completeness` | `force_synthesis`→synthesis | else llm_call |
| `_should_continue` (after llm_call) | `force_synthesis`→synthesis; `current_iteration>=25`→synthesis; last msg has tool_calls→tool_execute | else synthesis |
| `_after_tools` | `force_synthesis`→synthesis; `>=25`→synthesis | else llm_call |

`force_synthesis` is the universal "stop the turn, render the canned/advisor/
error message" signal honored by all four post-classifier routers.

### 6B.2 Intent classifiers
**`intent_classifier_builder`** (runs first; abstains `{}` if `mode!="builder"`):
7 buckets `BUILD_NEW, BUILD_MODIFY, EXPLAIN, COMPARE, RECOMMEND, KNOWLEDGE,
AMBIGUOUS` (`MIN_CONFIDENCE=0.55`). Regex shortcuts skip the LLM
(從零/新建/build a new → BUILD_NEW; 加一個/接到/改成/add a/remove → BUILD_MODIFY).
LLM returns `{intent, confidence, reason}`; low-confidence non-build → AMBIGUOUS.
Skill-step snapshots force BUILD_MODIFY/NEW. Sets `{intent:"builder_<bucket>",
intent_hint:reason}`.

**`intent_classifier`** (chat): buckets `clear_chart, clear_rca, clear_status,
knowledge, vague`. **`[intent=<id>]` prefix bypasses the LLM** →
`{intent:"clarified", user_message:cleaned}`. `vague` emits a `clarify` card +
`force_synthesis` + a synthetic AIMessage (canned reply, no extra LLM). Rule of
thumb encoded: a rule/algorithm name standing alone = knowledge; a target
("why is EQP-07 OOC") = clear_rca.

### 6B.3 `intent_completeness` (deterministic gate)
Bypasses (`{}`) for vague/clarified intents, non-`clear_` intents, and any
`[intent_confirmed:...]` / `[intent=...]` prefix. Otherwise one LLM call checks
three dimensions:
- **inputs** — did the user name equipment/lot/step/date? Emits only canonical
  names (`tool_id, step, lot_id, recipe_id, apc_id, time_range, threshold,
  object_name`).
- **logic** — what to compute (OOC rate / count / trend / cpk); flag only if
  vague verbs alone.
- **presentation** — 8-way enum (`line_chart, bar_chart, control_chart, heatmap,
  table, alert, mixed_table_alert, mixed_chart_alert`); "users skip this most, be
  strict."

`is_pipeline_request==false` or `complete==true` → `{}` (proceed). Incomplete →
emit `design_intent_confirm` card `{card_id:"intent-<8hex>", inputs:[normalized],
logic, presentation:<normalized>, alternatives:[]}` (inputs normalized via an
alias map equipment→tool_id, timeframe→time_range, etc.) + `force_synthesis`.

### 6B.4 `pre_clarify_check`, `advisor_dispatch`, dimensional clarifier
- **`pre_clarify_check`** (builder BUILD_*, pre-LLM): runs the dimensional
  clarifier; if dimensions fire, emit `design_intent_confirm` + `force_synthesis`
  + `synthesis_text_override` (a deterministic "I need to confirm N things" reply,
  rendered with no LLM).
- **`advisor_dispatch`**: bridges to the Block Advisor graph (EXPLAIN/COMPARE/
  RECOMMEND/AMBIGUOUS), streams `advisor_answer` events, returns the markdown as
  the final text. The advisor graph itself classifies then runs pure-function
  nodes that fetch every block fact from Java `/internal/blocks` at call time.
- **`dimensional_clarifier`**: deterministic detectors + LLM localization only.
  4 detectors (max 3 fire): scope-conflict (tool_id declared but msg says
  各機台/全廠 → single_via_param|all_machines|multi_via_list), metric-type
  (OOC but APC/SPC/FDC ambiguous), bar-x-axis (bar chart w/o x dim), time-grain
  (trend w/o bucket). One LLM call fills only question/label/hint in the user's
  language; canonical ids/values are immutable.
  `parse_resolutions_from_prefix("[intent_confirmed:<card> d1=A d2=B]")` →
  `{d1:A,d2:B}`; `augment_goal_for_resolutions` splices a deterministic
  `(dim,value)→sentence` hint into the build goal.

### 6B.5 `llm_call`
`MAX_LLM_ATTEMPTS=2`. Converts LangChain messages → v1 `(system, messages)`,
appends an intent-hint block if present. Prompt cache (gated): system wrapped as
a content block with `cache_control:{type:ephemeral}`, and the **last tool** also
stamped. Role gating: `_visible_tools(caller_roles)` = `TOOL_SCHEMAS` minus
`_LLM_HIDDEN_TOOLS` (always) minus `execute_skill` (PIPELINE_ONLY_MODE) minus
`_ON_DUTY_HIDDEN_TOOLS` (when `_is_on_duty_only`, fail-closed: empty roles =
ON_DUTY). `llm.create(..., max_tokens=8192, tools)`. **Usable = text OR
tool_calls.** Retry when exception/`stop_reason=='error'`/empty; persistent
failure → synthetic AIMessage + `force_synthesis` (graceful). `response_metadata`
carries `finish_reason` (raw provider) + cache token counts.

### 6B.6 `tool_execute`
Degenerate-loop self-test (`LOOP_THRESHOLD=3` over execute_mcp/execute_skill/
search_published_skills/invoke_published_skill) injects a `_loop_warning` the LLM
sees next iteration. Special cases:
- **`confirm_pipeline_intent`**: emits `design_intent_confirm` + result
  `{status:"awaiting_user_confirmation", _force_synthesis:true}` + a clean
  trailing AIMessage so synthesis doesn't dump raw JSON.
- **`build_pipeline_live`** (drives the builder graph):
  1. **Dimensional clarifier gate** — if the message doesn't start
     `[intent_confirmed:`, run `build_clarifications`; any fire → emit
     `design_intent_confirm` + `_force_synthesis`, build NOT run.
  2. **`_scrub_chat_notes`** — drop lines carrying (a) literal IDs (`EQP-\d+`,
     `LOT-\d+`…) when that role is a declared `$input` (they conflict with the
     parametric intent), (b) block prescriptions (`block_…`), (c) structural
     directives (「需對各機台查詢」「分別查詢」). The chat LLM auto-fills notes from
     active alarms that contradict the user's `$tool_id` intent; the builder must
     own block choice.
  3. **`_scrub_chat_goal`** — replace literal IDs with `$role` when declared,
     collapse `$X 和 $X` conjunctions, swap 全廠/各機台/所有機台 → `$tool_id 機台`
     (anti-scope-expansion).
  4. merge `parse_resolutions_from_prefix` + free-text picks; `augment_goal_…`.
  5. `show_plan` → `dry_run_plan` (no mutation). Else `stream_graph_build(
     instruction=scrubbed_goal, base_pipeline, session_id=uuid, skip_confirm=True,
     skill_step_mode)` — "the chat conversation IS the confirmation." Intercepts
     `judge_clarify_pending`/`intent_confirm_required` (re-emits with the **chat**
     session id, registers a pending record, breaks). Each event →
     `wrap_build_event_for_chat` → `pb_glass_*`. Captures `done.pipeline_json`.
  6. Post-build safety validator (`C10_UNDECLARED_INPUT_REF`) → `pb_glass_error`.
- **Auto-run** (status ∈ {finished,success} + native blocks): emit `pb_run_start`,
  `execute_native(pipeline_json)`, attach `auto_run` summary, emit `pb_run_done`
  (or partial / `pb_run_error`).

`_trim_result_for_llm` prefers `llm_readable_data` (≤4000 chars), strips heavy
keys (output_data, dataset, _data_profile) to protect the ReAct token budget.

### 6B.7 `synthesis` + `self_critique`
**`synthesis`**: `synthesis_text_override` short-circuits (no LLM). Else extract
text from the last message, strip `<plan>…</plan>`, resolve a contract via
`_resolve_contract` (**CHART 鐵律: always force `visualization=[]`** — discard
LLM-embedded viz; chart-already-rendered mode strips `<contract>` from the
visible text; else auto-build an SPC contract from `last_spc_result`).

**`self_critique`** (cheap-then-LLM): (1) deterministic ID-hallucination scan —
any `LOT-/STEP_/EQP-/APC-/RCP-` id in the final text but NOT in any tool result
is replaced `id⚠️[捏造]` + warning footer; (2) one bounded LLM
value-traceability check (timeout 12s, non-blocking) verifying every concrete
value (readings/timestamps/UCL/LCL/%) is traceable to executed tools, returning
`amended_text` that swaps unsourced numbers for `[查無資料]`. Result carried in
`reflection_result` for the SSE adapter to substitute.

---

## 6C. SSE events, confirm protocol, and the builder→chat bridge

### 6C.1 Event vocabulary
Builder terminal/pause: `done{status,pipeline_json,summary,session_id}`,
`goal_plan_confirm_required`, `confirm_pending`, `clarify_required`,
`handover_pending`, `judge_clarify_pending`, `phase_round_paused`. Builder
node-emitted: `goal_plan_proposed/confirmed`, `phase_round`, `phase_action`,
`phase_observation`, `phase_completed`, `phase_revise_started`,
`runtime_check_ok/failed`, `build_finalized`.

Chat surface (after the bridge): `pb_glass_start`, `pb_glass_op`, `pb_glass_chat`,
`pb_glass_error`, `pb_glass_done{pipeline_json}`, `pb_run_start`,
`pb_run_done{result_summary}`, `pb_run_error`, `design_intent_confirm`,
`pb_intent_confirm`, `pb_judge_clarify`, `plan`/`plan_update`, `synthesis`,
`done`.

### 6C.2 The two confirm protocols (don't conflate)
- **`design_intent_confirm` → `[intent_confirmed:CARD]` re-POST** (intent
  ambiguity, before/around a build): ambiguity → emit card with `card_id` +
  deterministic `clarifications` + force-synthesis to end the turn. The user picks
  → re-POSTs the message prefixed `[intent_confirmed:<id> dim=val ...]` with the
  **same chat session_id**. Classifiers/completeness bypass on that prefix;
  `parse_resolutions_from_prefix` + `augment_goal_for_resolutions` splice picks
  into the goal deterministically.
- **`/chat/intent-respond`** (resumes a *paused build*'s judge/clarify
  `interrupt`): keyed by the chat session id via `pending_judge`/`pending_clarify`.

The chat↔build session distinction is load-bearing: pause cards carry
`session_id = chat session` (what the card POSTs back) and `build_session_id =
build uuid` (trace correlation).

### 6C.3 The builder→chat event bridge (`event_wrapper.py`)
`wrap_build_event_for_chat(evt, session_id)` is the **only** place builder events
become `pb_glass_*` (the frontend chat panel + Lite Canvas know only `pb_glass_*`).
**Critical invariant — raw structured args must be preserved, not flattened to
text:** `phase_action` passes raw `tool_args_raw`/`action_result_raw` as the
top-level `args`/`result` (v30 phase context stashed under underscore keys
`_phase_id`/`_round`/`_summary`) so the frontend `applyGlassOp` can still mutate
the canvas. Flattening to a text summary made the Lite Canvas invisible — this is
the codified "event wrappers keep raw structured args" rule. `_v2_op_to_v1_args`
translates typed ops → the `{block_name,params}` / `{from_node,to_node}` /
`{node_id,key,value}` shapes the frontend applies. `pb_judge_clarify` returns
None here (the canonical emit is from `tool_execute` with the chat session id) to
avoid a duplicate card; internal events (phase_round, phase_observation,
confirm_pending, inspection_*) → None.

### 6C.4 LLM client (`agent_helpers_native/llm_client.py`)
`get_llm_client(force_provider?)` reads `LLM_PROVIDER` (cached singleton):
`anthropic` (native system/tools + prompt cache via `cache_control`), `ollama`
(any OpenAI-compatible endpoint — **production**, KIMI K2.5 default, pins
`provider.order=["Fireworks"]` for cache passthrough), `internal-proxy`.
`create(system, messages, max_tokens, tools?)` → `LLMResponse{text, stop_reason
(normalized: stop/length/eos→end_turn, tool calls→tool_use), finish_reason (RAW
provider value — diagnoses truncation vs provider-error vs JSON-parse bug),
content, input/output_tokens, cache_*_tokens}`. The client does **no** retry —
bounded retry lives in callers (chat `llm_call`, builder `goal_plan`). The
OpenAI-compat path converts Anthropic tool_use/tool_result ↔ function-calling,
parses XML tool calls for Kimi-style models, strips `<think>` blocks. Single model
switch: sidecar `.env` `OLLAMA_MODEL` + `LLM_PROVIDER`; KIMI via Fireworks is the
cost-right default (only provider keeping prompt cache).

### 6C.5 Build trace (`/admin/build-traces`)
`BuildTracer` writes one JSON per build to `/tmp/builder-traces/*.json` (NOT a DB
table): plan, every LLM call (`user_msg` + `raw_response` + `finish_reason`),
every graph step, verifier verdicts. A `trace_summary` renderer produces Plan →
stuck phase → per-round history (same model powers the admin Summary tab + the
`/verify-build` tool). `trace_replay` re-runs a single saved LLM call under
controlled variants ("would changing X have changed the pick?").

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
