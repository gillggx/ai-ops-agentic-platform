# aiops-app — Spec

**Date:** 2026-04-26
**HEAD:** 778df37+ (in flight)
**Status:** Living Document（依 code 實況萃取）

---

## 1. 定位

AIOps 平台的 **Frontend 應用層**（Next.js 15 standalone）。三個視角：

- **Operations Center** — 值班工程師 / 全角色：告警看板、Dashboard AI Briefing、AI Agent 對話、設備下鑽
- **Knowledge Studio** — PE / IT_ADMIN：Pipeline Builder（單一建構入口，2026-04-23 後 Auto-Patrols / Diagnostic Rules / My Skills 統一收進來）
- **Admin** — IT_ADMIN：Triggers Overview、Skills、Memory、Data Sources、Event Registry、System Monitor、Users

**邊界：** 不寫商業邏輯，只做 UI 渲染 + API proxy。Frontend `/api/*` route 一律 proxy 到 Java :8002（透過 `FASTAPI_BASE_URL` env）。LLM key 不放這裡（除了 frontend 自用 `@anthropic-ai/sdk` 0.80，幾乎不用）。

## 2. 技術棧

| Category | Tech | Version |
|---|---|---|
| Framework | Next.js (App Router, standalone) | 15.2.4 |
| React | – | 19.0.0 |
| Lang | TypeScript（strict） | 5.x |
| Auth | NextAuth v5 beta | 5.0.0-beta.31 |
| Chart (declarative) | Vega-Lite + Vega + vega-embed | 5.21 / 5.30 / 6.26 |
| Chart (interactive) | Plotly.js dist-min + react-plotly | 3.4 / 2.6 |
| Graph Layout | @xyflow/react + dagre | 12.10 / 2.0 |
| Markdown | react-markdown + remark-gfm | 10.1 / 4.0 |
| Resize Panel | react-resizable-panels | 4.10 |
| Contract | aiops-contract（local file:） | 0.1.0 |
| AI SDK | @anthropic-ai/sdk（很少用） | 0.80 |
| E2E | Playwright | 1.59 |

## 3. App Router 路徑

```
src/app/
├── layout.tsx                root — SessionProviderWrapper + AppShell
├── page.tsx                  redirect("/dashboard")
├── globals.css
├── login/                    ★ NextAuth v5 login（OIDC + credentials）
│   ├── page.tsx              server: 列舉 providers + searchParams
│   └── LoginClient.tsx       client form
├── dashboard/                Operations Center 主頁（左告警 / 右設備 / 底 Quick Diagnostics）
├── alarms/                   全廠告警看板
├── events/                   全廠事件記錄（Agent handoff target）
├── lots/                     批次追蹤（Agent handoff target）
├── topology/                 製程物件拓撲圖（隱藏路由，Topology layout 全屏）
├── chat/                     Agent 對話頁
├── prototype/                UI prototype 展示（dev-only）
├── me/                       ★ 個人帳戶
│   ├── profile/              帳號設定（display_name）
│   ├── change-password/      密碼變更
│   └── memories/             我的長期記憶（per-user）
├── admin/                    ★ Knowledge Studio + Admin（多重 role）
│   ├── pipeline-builder/     ⭐ 單一建構入口（取代 Skills/Patrols/Rules 三套表單）
│   ├── triggers/             Triggers Overview — Auto-Patrols + Auto-Check Rules + Published Skills
│   ├── auto-patrols/         legacy CRUD（仍保留）
│   ├── auto-check-rules/     legacy CRUD
│   ├── published-skills/     legacy
│   ├── automation/           catch-all proxy
│   ├── memories/             Agent Memory（admin 視角）
│   ├── mcps/                 MCP 管理
│   ├── system-mcps/          System MCP 列表
│   ├── event-types/          Event Type 管理
│   └── users/                ⭐ Users CRUD + role 變更 + role-history（IT_ADMIN only）
├── system/                   IT 設定
│   ├── data-sources/, event-registry/, monitor/, skills/, scripts/, cron-jobs/
└── api/                      ★ 65 個 proxy route.ts
```

## 4. 模組樹（src/）

```
src/
├── auth.ts                  NextAuth v5 config — Azure AD / Google / Keycloak / Okta + Credentials
├── middleware.ts            redirect 未登入 → /login（受 AIOPS_AUTH_REQUIRED gating）
├── app/                     App Router pages + API proxies (見 §3)
├── components/
│   ├── shell/AppShell.tsx   ★ 頂層 layout — Topbar + Sidebar + main + AI Agent panel
│   │                          含 ShellGate（隱藏 shell 在 /login + /api/auth/*）
│   ├── shell/SessionProviderWrapper.tsx
│   ├── layout/Topbar.tsx    ★ user 下拉選單（avatar + role badges + 帳號設定 / 變更密碼 / 我的記憶 / 登出）
│   ├── layout/AnalysisPanel.tsx          ContractRenderer overlay
│   ├── layout/DataExplorerPanel.tsx
│   ├── copilot/AIAgentPanel.tsx          AI Agent 對話面板
│   ├── copilot/LiveCanvasOverlay.tsx     ★ Glass Box 即時建構畫布（pb_glass_* 事件）
│   ├── copilot/ChartIntentRenderer.tsx
│   ├── copilot/ContractCard.tsx
│   ├── copilot/PipelineConsole.tsx + PbPipelineCard.tsx + PbPatchProposalCard.tsx
│   ├── pipeline-builder/    ★ 28 個 component — Builder Canvas + Block Library + Triggers Wizard
│   ├── contract/            ContractRenderer / EvidenceChain / SuggestedActions
│   ├── chat/                ChatPanel
│   ├── ontology/            TopologyCanvas / EquipmentDetail / OverviewDashboard
│   ├── operations/          AlarmCenter / SkillOutputRenderer
│   ├── admin/               admin 頁面共用 component
│   ├── skill-builder/ClarifyDialog.tsx   inline clarification modal
│   ├── McpChartRenderer.tsx
│   └── common/
├── context/AppContext.tsx   單一 Context Provider
├── lib/
│   ├── auth-proxy.ts        ★ getBearerToken / authHeaders — proxy route 共用
│   ├── sse.ts               SSE 解析
│   ├── store.ts             local store helpers
│   └── pipeline-builder/    builder 共用工具
├── mcp/catalog.ts           前端 MCP catalog（19 個，餵給 Agent system prompt）
└── types/                   全域 TS type
```

## 5. 認證 / 授權

### 5.1 NextAuth v5 multi-provider（[src/auth.ts](aiops-app/src/auth.ts)）

| Provider | Env 條件 | 說明 |
|---|---|---|
| Azure AD | `OIDC_AZURE_CLIENT_ID + SECRET` | tenant 透過 `OIDC_AZURE_TENANT_ID` 指定，default `common/v2.0` |
| Google | `OIDC_GOOGLE_CLIENT_ID + SECRET` | – |
| Keycloak | `OIDC_KEYCLOAK_CLIENT_ID + ISSUER` | + secret |
| Okta | `OIDC_OKTA_CLIENT_ID + ISSUER` | + secret |
| **Credentials (Local)** | **永遠啟用** | username/password → POST `/api/v1/auth/login` 拿 Java JWT |

### 5.2 OIDC upsert flow

OIDC sign-in 成功後：
1. NextAuth `signIn` callback 收到 `provider` + `sub`
2. POST Java `/api/v1/auth/oidc-upsert`（`X-Upsert-Secret: AIOPS_OIDC_UPSERT_SECRET`）
3. Java 找/建本地 user，回 `(access_token, user.roles, user.id)`
4. NextAuth jwt callback 把 `javaJwt + roles + provider + userId` 寫進 token

→ Session 含 `roles`，所有 proxy route 用 [authHeaders()](aiops-app/src/lib/auth-proxy.ts) 帶 Java JWT 出去。

### 5.3 Middleware 強制登入（[middleware.ts](aiops-app/src/middleware.ts)）

```
matcher: 全部，除 _next/static, _next/image, favicon
PUBLIC_PATHS = /login, /api/auth, /_next, /favicon
未登入 + AIOPS_AUTH_REQUIRED=1 → redirect 到 /login（用 x-forwarded-host 拼 origin）
未登入 + AIOPS_AUTH_REQUIRED!=1 → 放行（legacy shared-token mode）
```

### 5.4 Role-based menu filter（[AppShell.tsx:46-76](aiops-app/src/components/shell/AppShell.tsx#L46-L76)）

```ts
OPS_ITEMS       → all roles            # Alarm + Dashboard
KNOWLEDGE_ITEMS → PE + IT_ADMIN         # Pipeline Builder
ADMIN_ITEMS     → IT_ADMIN only         # Triggers / Skills / Memory / Data / Events / Monitor / Users
```

Role 名來自 session `roles`（值 `IT_ADMIN | PE | ON_DUTY`，與 Java 一致）。Empty roles → 渲染空 sidebar（不再 fallback 全開）。

### 5.5 ShellGate（[AppShell.tsx:386-394](aiops-app/src/components/shell/AppShell.tsx#L386-L394)）

`/login` + `/api/auth/*` 不渲染 Shell（沒 Topbar / Sidebar / AI Agent panel），只渲染 children。

## 6. API Proxy Layer

**65 個 route.ts**，全部透過 [authHeaders()](aiops-app/src/lib/auth-proxy.ts) 拿 token：

```ts
// 統一 pattern
const token = (await authHeaders()).Authorization;
const r = await fetch(`${FASTAPI_BASE_URL}/api/v1/...`, {
  headers: { Authorization: token, ... },
});
```

| 主要 prefix | upstream（Java 接管後） |
|---|---|
| `/api/auth/[...nextauth]` | NextAuth route handler（不 proxy） |
| `/api/me/{profile,password,memories}` | Java `/api/v1/auth/me/*` + per-user memory |
| `/api/admin/users-manage[/...]` | Java `/api/v1/admin/users` |
| `/api/admin/auto-patrols[/...]` | Java `/api/v1/auto-patrols` |
| `/api/admin/alarms[/...]` | Java `/api/v1/alarms` |
| `/api/admin/rules[/...]` | Java `/api/v1/diagnostic-rules` |
| `/api/admin/memories[/...]` | Java `/api/v1/agent-memories` (or `/internal/agent-memories`) |
| `/api/admin/mcps[/...]` | Java `/api/v1/mcp-definitions` |
| `/api/admin/event-types[/...]` | Java `/api/v1/event-types` |
| `/api/admin/automation/[...path]` | Java catch-all |
| `/api/admin/briefing` | Java `/api/v1/briefing` SSE |
| `/api/admin/monitor` | Java `/api/v1/admin/monitor` |
| `/api/admin/agent` | Java `/api/v1/agent/*` |
| `/api/agent/{chat,build,build/stream/[id], session, approve}` | Java `/api/v1/agent/*`（Java 再 SSE proxy 到 sidecar） |
| `/api/pipeline-builder/{blocks,validate,pipelines,...}` | Java `/api/v1/pipeline-builder/*` |
| `/api/ontology/[...path]` | Java（因 ontology MCP 在 Java DB） |
| `/api/mcp-catalog` | 前端 store + `src/mcp/catalog.ts` 合併 |

## 7. AI Agent panel — Glass Box + Plan + Auto-Run

[copilot/AIAgentPanel.tsx](aiops-app/src/components/copilot/AIAgentPanel.tsx) + [LiveCanvasOverlay.tsx](aiops-app/src/components/copilot/LiveCanvasOverlay.tsx) + [PlanRenderer.tsx](aiops-app/src/components/copilot/PlanRenderer.tsx)（v1.4 新增）：

**Build 流程（native，由 sidecar Glass Box agent 直發）：**
1. 使用者打 `build_pipeline_live` → SSE 串流：
2. `pb_glass_start` → 開 LiveCanvasOverlay 空畫布
3. `pb_glass_op` × N → node-by-node 增量繪 canvas
4. `pb_glass_chat` → 旁白文字
5. `pb_glass_done` → 顯示 final summary + pipeline_json
6. **v1.4：** sidecar 自動 chain `execute_native(pipeline_json)` → 觸發 `pb_run_*` events
7. AIAgentPanel 從 `pb_run_done.node_results` 抽 chart_intents → 組成 synthetic AIOpsReportContract → 開中央 AnalysisPanel

**Chat 流程：** SSE 走 LangGraph 完整 stages → 回傳 [AIOpsReportContract](../aiops-contract/SPEC.md)，由 [ContractRenderer](aiops-app/src/components/contract/ContractRenderer.tsx) 渲染到 [AnalysisPanel](aiops-app/src/components/layout/AnalysisPanel.tsx)。

**v1.4 Plan Panel（[PlanRenderer.tsx](aiops-app/src/components/copilot/PlanRenderer.tsx)）：**
- 每個 turn agent 第一個 tool call 是 `update_plan(action="create")` → 吐 3-7 個 todo
- 後續每完成一階段呼叫 `update_plan(action="update", id, status="done")`
- Frontend 收 `plan` / `plan_update` SSE event → in-place 更新 checklist
- 狀態：pending ○ / in_progress ◐（脈動） / done ✓（劃線） / failed ✕
- **Plan dedupe**：每輪 build 只應該有 1 張 plan card。AIAgentPanel 用 `currentPlanMsgIdRef` 追蹤當輪 plan 訊息 id，若 agent 違規再 `create` 一次（雖然 prompt 已禁止），就**就地替換 items**而非疊新卡。新 build 開始時 ref reset 為 null。

**v1.4 Auto-Run banner：**
- `pb_run_start` → 顯示「▶ Auto-Run 執行中（N nodes）」
- `pb_run_done` → 顯示「✓ 完成 (N ms)」+ 結果丟去 AnalysisPanel
- `pb_run_error` → 顯示紅 banner，LLM 自動跟進 `propose_pipeline_patch`

**所有圖表只在中央 AnalysisPanel 渲染**，AI Agent panel 只顯示文字 + Plan + 動作按鈕。

### 7.2 Builder Mode Block Advisor (2026-05-02)

`/internal/agent/build` 不再只負責「建 pipeline」— 入口先 **graph-level intent classifier** 把訊息分為 5 桶：

| Intent | 路由 | UI 表現 |
|---|---|---|
| `BUILD` | 既有 Glass Box `stream_agent_build` | canvas 增量繪製 + plan card |
| `EXPLAIN` | `advisor.stream_block_advisor` → fetch 1 block from Java → markdown | 黃底 advisor 卡（📖 Block 說明） |
| `COMPARE` | fetch ≥2 blocks → markdown table | 黃底 advisor 卡（⚖️ Block 對比） |
| `RECOMMEND` | keyword search registry → top-3 + rationale | 黃底 advisor 卡（💡 Block 推薦） |
| `AMBIGUOUS` | 直接 yield 澄清訊息（無 LLM call） | 黃底 advisor 卡（🤔 請再說明） |

**設計原則**：flow 全在 graph、LLM 只做 reasoning。advisor 從不擁有 tool list — classifier 決 bucket 後，每個 bucket 走**固定** node 序列：classify → extract（抽 block 名 / 關鍵字）→ fetch（Java `/internal/blocks`，always-fresh）→ synthesize（markdown）。詳見 [CLAUDE.md "Agent Behaviour Principles"](../CLAUDE.md)。

**為什麼 fetch 走 Java 而不是 sidecar in-process registry**：BlockRegistry 是 boot-time snapshot；改 description 後 sidecar 不重啟看不到。advisor 每次 `JavaAPIClient.get_block_by_name` 拿到當下最新版本，符合 CLAUDE.md「Block Description 是唯一文件來源」原則。

**SSE event 新類型**：`advisor_answer { kind, markdown, ... }`（type literal 在 [agent_builder/session.py](python_ai_sidecar/agent_builder/session.py)）。`done` 事件帶 `status: "advisor_done"` 讓前端知道**不要**跑 auto-layout（canvas 沒被 mutate）。

### 7.1 ChartDSL — multi-series overlay (`series_field`)

[SkillOutputRenderer.tsx → renderLineBarScatter](aiops-app/src/components/operations/SkillOutputRenderer.tsx) 處理 ChartDSL spec。當 spec 帶 `series_field` 且 `primaryY.length === 1` 時：

- 把 `data` rows 依 `series_field` 的值分組 → 每組一條 Plotly trace（自動套 SERIES_COLORS palette）
- UCL / LCL / Center / sigma 線 / OOC highlight 仍以**全域 rules** 疊加（不是 per-group）
- Legend 強制開啟（`showlegend = primaryY.length > 1 || secondaryY.length > 0 || Boolean(seriesField)`），讓 user 看得出哪條線是哪個 toolID / lotID

→ 對應 sidecar 端 `block_chart` 在 SPC mode 同時 emit `series_field`，frontend 不需要為了多色 line 改寫渲染分支。

## 8. Pipeline Builder（Knowledge Studio 唯一入口）

[components/pipeline-builder/](aiops-app/src/components/pipeline-builder/)（28 個 component）：

| Component | 用途 |
|---|---|
| `BuilderLayout.tsx` | 主 layout — Block Library 左 / Canvas 中 / Inspector 右 |
| `BlockLibrary.tsx` + `BlockDocsDrawer.tsx` + `CategoryIcon.tsx` | 27 個 block 目錄（從 Java `/internal/blocks` 拉，類別 + examples） |
| `AgentBuilderPanel.tsx` | Glass Box build SSE → LiveCanvasOverlay；2026-05-02 起也渲染 Block Advisor 的 markdown 卡（黃底，`role: "advisor"`）|
| `AutoPatrolSetupModal.tsx` + `AutoPatrolTriggerForm.tsx` | Patrol kind + trigger wizard（兩步） |
| `AutoCheckPublishModal.tsx` + `AutoCheckTriggerForm.tsx` | Auto-Check Rules（綁 alarm attribute） |

**UX 約定（2026-04-23 phase α）：** Knowledge Studio menu 只剩 **Pipeline Builder** 一條，所有 publish kind（Patrol / Check / Skill）在 Builder 內 modal 切換。Auto-Patrols / Diagnostic Rules legacy CRUD 頁面仍在 `/admin/`，但是 secondary 入口。

## 9. State Management

```typescript
// AppContext（唯一 Context）
{
  selectedEquipment: { equipment_id, name, status } | null
  triggerMessage: string | null            // 觸發 Agent 查詢
  contract: AIOpsReportContract | null     // 分析結果 → AnalysisPanel
  investigateMode: boolean                 // 切換調查模式
  dataExplorer: DataExplorerState | null   // 資料探勘面板
}
```

NextAuth session：透過 `useSession()` 取 — 含 `roles / javaJwt / userId / provider`。

## 10. Build / Deploy

- **Local：** `npm run dev`（Next.js 15 dev）
- **Build：** `npm run build` → `.next/standalone/`
- **Prod：** systemd unit [deploy/aiops-app.service](deploy/aiops-app.service)
  ```
  ExecStart=/usr/bin/node .next/standalone/server.js
  EnvironmentFile=/opt/aiops/aiops-app/.env.local
  ```
  - 用 Next.js `output: "standalone"` — 不需要 `node_modules`，整個 server.js + .next/static 自帶
  - 部署時 update.sh 會 `cp -r .next/static .next/standalone/.next/static`

## 11. 環境變數（[.env.example](aiops-app/.env.example) + 實際 .env.local）

| Variable | Default | 說明 |
|---|---|---|
| `FASTAPI_BASE_URL` | `http://localhost:8001` → 實際 prod `http://localhost:8002` | Backend proxy target（已切 Java） |
| `AGENT_BASE_URL` | 同上 | Agent SSE proxy target |
| `ONTOLOGY_BASE_URL` | `http://localhost:8012` | （透過 Java 取，目前不直連） |
| `INTERNAL_API_TOKEN` | – | legacy shared bearer（fallback when no session） |
| `ANTHROPIC_API_KEY` | – | frontend 自用 SDK（很少觸發） |
| `AIOPS_AUTH_REQUIRED` | – | `1` 啟用嚴格登入；未設仍 legacy fallback |
| `NEXTAUTH_SECRET` | – | NextAuth session 簽章 |
| `NEXTAUTH_URL` | – | callback origin |
| `OIDC_AZURE_*`, `OIDC_GOOGLE_*`, `OIDC_KEYCLOAK_*`, `OIDC_OKTA_*` | – | 4 個 IdP，設了才註冊 |
| `AIOPS_OIDC_UPSERT_SECRET` | – | NextAuth → Java oidc-upsert 共用密鑰 |

## 12. 已知缺口

1. **65 個 proxy route 散落** — 沒有自動化 OpenAPI client；新增 endpoint 必須在 Frontend 手刻 route.ts，容易漏
2. **`@anthropic-ai/sdk` 0.80 留在 deps 但幾乎不用** — Glass Box 早期路徑遺留，可移除減少 bundle
3. **`mcp/catalog.ts` 與 Java DB 並存** — 前端 hardcode 19 MCP，與 DB 不一致時 Agent 會誤導
4. **legacy admin 頁面（auto-patrols/, auto-check-rules/, published-skills/）** 仍存在 — Pipeline Builder UX 收編後尚未刪除
5. **`prototype/` 目錄** 是 dev-only，無 route guard — IT_ADMIN 也能誤入
6. **無 i18n** — UI 中文/英文/日文混用
7. **react 19 + next 15 + Plotly + Vega 一起 bundle** — `.next/standalone` 體積偏大；未做 dynamic import 分塊
8. **`AIOPS_AUTH_REQUIRED` 預設為空** — prod 沒手動設就是 legacy fallback

## 13. 變更指南

### 加新 API proxy
1. 在 `app/api/<scope>/route.ts` 寫 GET/POST
2. **必用** [authHeaders()](aiops-app/src/lib/auth-proxy.ts) 而非自己 `process.env.INTERNAL_API_TOKEN`
3. 回傳維持 `{ status, message, data, error_code }` Java 格式

### 加新 page route
1. 在 `app/<segment>/page.tsx`
2. 若需登入：middleware 已自動擋（不在 PUBLIC_PATHS）
3. 若需特定 role：用 `useSession()` 加上 client-side check（IT_ADMIN-only 也應在 server 端 Java endpoint 加 `@PreAuthorize`，**不能**只靠前端隱藏）

### 加新 OIDC provider
1. `auth.ts` 加 import + provider env-gated push
2. `availableProviders()` 自動把它列出來給 LoginClient
3. NextAuth jwt + signIn callback 會自動接（共用 `oidc-upsert` flow）

### 新增 role
1. Java [Role.java](../java-backend/src/main/java/com/aiops/api/auth/Role.java) + [Authorities.java](../java-backend/src/main/java/com/aiops/api/auth/Authorities.java) + RoleHierarchy
2. Frontend [AppShell.tsx](aiops-app/src/components/shell/AppShell.tsx) `userCanSeeXxx` 加判斷
3. session typing 不需改（roles 是 string[]）

### Glass Box 事件擴充
1. 後端新增 SSE event kind（在 sidecar `agent_builder/orchestrator.py`）
2. Frontend 在 [AIAgentPanel.tsx](aiops-app/src/components/copilot/AIAgentPanel.tsx) 加 callback prop（`onGlassXxx`）
3. [AppShell.tsx](aiops-app/src/components/shell/AppShell.tsx) 把 callback wire 到 `LiveCanvasOverlay`
