# AIOps Platform — Project Handoff Document

**Version:** 2.0
**Date:** 2026-04-07
**Author:** Gill (Tech Lead)
**Audience:** Product Manager、DevOps Engineer

---

## 1. 產品概述

### 1.1 這是什麼？

AIOps 是一個專為**半導體製造廠 (FAB)** 設計的 AI Agent 平台。製程工程師 (PE) 不需要寫程式，透過自然語言對話就能完成：

- **製程異常根因分析 (RCA)** — 「EQP-03 最近為什麼一直 OOC？」
- **設備狀態診斷** — 「看一下 STEP_059 所有的 SPC charts」
- **自動化巡檢** — 系統每 N 分鐘自動檢查 OOC 並建立告警
- **AI 輔助建立診斷規則** — 用自然語言描述檢查邏輯，AI 自動產生 Python 程式碼

### 1.2 核心價值主張

| 對象 | 痛點 | AIOps 解決方案 |
|------|------|---------------|
| 值班工程師 | 每天花 2-3 小時手動查 SPC 報表、追蹤異常批次 | AI Copilot 即時對話分析，一問一答就能定位根因 |
| 資深 PE | 診斷邏輯散落在 Excel/Word，無法系統化傳承 | Knowledge Studio：My Skills 儲存個人分析、可升級為 Auto-Patrol / Diagnostic Rule |
| IT 管理員 | 資料源分散，每次新增查詢要改程式碼 | Data Sources 管理介面，加新 API 不用改 code |

### 1.3 Live Demo

**Production URL:** https://aiops-gill.com/
**Login:** admin / admin

---

## 2. 系統架構

### 2.1 三層架構圖

```
                         使用者 (瀏覽器)
                              │
                           HTTPS
                              │
                         ┌────▼────┐
                         │  Nginx  │  SSL termination + reverse proxy
                         └────┬────┘
                              │
         ┌────────────────────┼───────────────────────┐
         │                    │                         │
    ┌────▼─────┐    ┌────────▼────────┐    ┌──────────▼──────────┐
    │ aiops-app │    │ fastapi_backend │    │ ontology_simulator  │
    │ (Next.js) │    │   (FastAPI)     │    │    (FastAPI)        │
    │ Port 8000 │───▶│   Port 8001    │───▶│    Port 8012        │
    │           │    │                 │    │                     │
    │ Frontend  │    │ AI Agent Core   │    │ 製程資料模擬器       │
    │ UI 渲染   │    │ Platform API    │    │ MongoDB             │
    └───────────┘    │ PostgreSQL      │    └─────────────────────┘
                     │ + pgvector      │
                     └─────────────────┘
```

### 2.2 四個 Project

| Project | 技術棧 | 職責 | Port |
|---------|--------|------|------|
| **aiops-app** | Next.js 15 + React 19 + TypeScript | 前端 UI（三欄 layout：Sidebar + Main + AI Copilot） | 8000 |
| **fastapi_backend_service** | FastAPI + PostgreSQL + pgvector + LangGraph | AI Agent、Skill 管理、Auto-Patrol、Memory | 8001 |
| **ontology_simulator** | FastAPI + MongoDB + NATS | 模擬半導體廠的 LOT/TOOL/SPC/APC/DC 資料 | 8012 |
| **aiops-contract** | TypeScript + Python (dual package) | Agent ↔ Frontend 的共用型別定義 | — |

### 2.3 資料流

```
使用者輸入問題
  → aiops-app (Next.js) 透過 SSE 串流到 backend
    → Agent Orchestrator (LangGraph v2)
      → Stage 1: Context Load (Soul Prompt + Memory + MCP Catalog)
      → Stage 2: LLM Call (Claude)
      → Stage 3: Tool Execute (MCP → OntologySimulator API)
      → Stage 3.5: ChartMiddleware (output_schema type → chart DSL 自動生成)
      → Stage 4: Synthesis (生成回覆 + AIOpsReportContract)
      → Stage 5: Self-Critique (反思檢查)
      → Stage 6: Memory Lifecycle (學習經驗寫入)
    → SSE events 串流回前端
  → aiops-app 渲染：文字在 Copilot 面板，圖表在 Analysis Panel
```

---

## 3. 功能模組詳解

### 3.1 Operations Center（值班工程師日常使用）

#### Dashboard（首頁 `/`）

- **設備總覽**：10 台機台即時狀態（running/idle/alarm/maintenance）
- **KPI 卡片**：稼動率、運行中設備數、告警數、維護中數
- **Quick Diagnostics**：一鍵問 AI 常見問題
- 點擊設備卡片 → 進入 Equipment Detail（DC 趨勢、SPC 管制圖、事件記錄）

#### Alarm Center（`/alarms`）

- Auto-Patrol 自動觸發的告警列表
- 支援 severity 篩選（CRITICAL / HIGH / MEDIUM / LOW）
- 支援 status 篩選（OPEN / 已認領 / 全部）
- **點擊告警 → Modal 彈窗**，兩個 Tab：
  - **觸發事件 (Trigger Event)**：Auto-Patrol 為什麼觸發（e.g. 「3/5 OOC in last 5 processes」）
  - **診斷分析 (Diagnostic Analysis)**：Diagnostic Rule 的深度分析結果（e.g. APC 趨勢是否異常）

#### AI Copilot（右側面板，永遠可見）

- 自然語言對話，SSE 串流回應
- 6-Stage 透明推理過程（使用者看得到每個 stage 的進度）
- 支援 20 種工具呼叫（查 SPC、查事件歷史、執行 Skill 等）
- 圖表結果顯示在中央 Analysis Panel（不在 Copilot 內）
- 對話 session 支援滑動視窗 + 階層摘要（context 不會爆）

### 3.2 Knowledge Studio（資深 PE 建立知識）

#### My Skills（`/admin/my-skills`）— NEW

- **使用者個人 Skill 庫**：從 Agent 對話中「儲存為我的 Skill」，或在 My Skills 頁面直接建立
- LLM 生成 steps（SSE 串流）、編輯、Try-Run sandbox 測試、刪除
- **升級機制**：My Skill 可提升為 Auto-Patrol（`binding_type=event`）或 Diagnostic Rule（`binding_type=alarm`）
- 統一 Skill 架構：所有 Skill 共用 `skill_definitions` 表，以 `source` + `binding_type` 區分用途

#### Inline Clarification（表單建立中斷式補問）— 2026-04-09

原本的 Interactive Skill Authoring（多輪對話式 `SkillAuthoringChat` + `skill_authoring_sessions` table + 8 個 `/skill-authoring` endpoints）已全面移除。取而代之的是一個更輕量的設計：**3 個 admin 頁面保留既有的表單建立流程，只在真正需要時插入一次 clarification 中斷。**

**架構決策理由：**

原本的 authoring 設計做了一個錯誤假設：Skill 建立需要獨立的對話模式。實際上：

- **Auto-Patrol / Diagnostic Rule** 的 `input_schema` 是觸發事件自動注入的 — 使用者永遠不該被問「這個 Skill 的 input 長什麼樣？」
- **My Skill** 的 input 是呼叫端提供的，也不是使用者該回答的問題
- **唯一合理的 user-facing 問題**：模糊的商業邏輯（時間窗口 N days、threshold、ID 對比還是值對比）

因此決定把既有的 3 個表單建立流程全部保留，只在 description 真正缺關鍵資訊時做一次中斷式補問。

**新流程（inline clarification）：**

```
使用者在 My Skills / Auto-Patrols / Diagnostic Rules 頁面填表 → 按「生成」
  → Backend generate-steps/stream 進入 Phase 0 quick_clarify_check
      ├─ 資訊足夠 → 直接進 Phase 1~2b，正常 stream steps_mapping
      └─ 需要補問 → SSE yield "clarify_needed" + questions → 結束
           ↓
     Frontend 彈出 ClarifyDialog (520px form modal，非 chat UI)
       ├─ 1~2 個問題，每題 button options + optional freetext + 預設值
       └─ 使用者確認 → 把答案 append 到 description → 以 skip_clarify=true 重打一次
           ↓
     Phase 0 跳過 → 正常 stream
```

**Backend：**
- `DiagnosticRuleService.quick_clarify_check()` — 輕量 Phase 0 LLM call，嚴格 prompt 禁止問 input 來源 / output 格式 / MCP 選擇 / 已提供的值
- `generate_steps_stream()` 在開頭多了 Phase 0 分支，SSE event 新增 `clarify_needed`
- `GenerateRuleStepsRequest.skip_clarify: bool` 新欄位
- Agent v2 system prompt 新增「模糊問題的處理原則」規則：預設直接執行，只在真的缺關鍵值時問 1 個問題（e.g.「最近」沒給 N days）；禁止把 toolID/lotID/objectName 當成 user-facing 選項問

**Frontend：**
- 新元件 `ClarifyDialog.tsx`（傳統 form，不是 chat）
- 3 個 admin 頁面的 `handleGenerate` 拆成 outer + `runGenerateStream(desc, skipClarify)`，遇到 `clarify_needed` 停止 streaming、開 dialog，使用者確認後帶 `skip=true` 重新呼叫

**E2E 驗證（3/3 pass）：**
- 「STEP_072 c_chart 7 天 spc chart」→ 直接執行（無問題）
- 「EQP-01 最近的 OOC 趨勢」→ 問一次「7 天還是 30 天？」
- 「STEP_020 SPC xbar 最近 14 天」→ 直接執行

#### Auto-Patrols（`/admin/auto-patrols`）

- **自動巡檢排程**：Cron 或 Event 驅動
- 每次巡檢執行一個 Skill（Python 腳本），判斷 `condition_met`
- 條件達成 → 自動建立 Alarm（severity + evidence）
- 可觸發 Diagnostic Rule 做深度分析

**範例 Auto-Patrol：**
> 「SPC continue OOC check」— 每次收到 OOC 事件，檢查該機台最近 5 次 process 是否有 >= 2 次 OOC。若是，觸發 HIGH 告警。

#### Diagnostic Rules（`/admin/skills`）

- **AI 兩階段生成**：
  1. Phase 2a：從自然語言描述拆解為多個 step（step plan）
  2. Phase 2b：逐 step 生成 Python 程式碼
- 支援 SSE 串流觀看生成過程
- Try-Run sandbox 測試
- 可從 Agent ad-hoc 分析 **一鍵提升 (promote)** 為永久 Rule

**範例 Diagnostic Rule：**
> 「SPC OOC - APC trending check」— 當 SPC OOC 告警觸發後，檢查 APC 參數是否有上升趨勢，判斷是否需要人工介入。

### 3.3 Admin（IT 管理員）

#### Skills（`/system/skills`）

- 所有 Skill 的總覽（統一架構：source + binding_type 決定用途）
- 點擊展開查看完整結構：Steps（含 Python code）、Input/Output Schema、Metadata

#### Agent Memory（`/admin/memories`）

- AI 長期記憶管理
- pgvector 1024-dim embedding（bge-m3 模型）
- 反思式生命週期：Write → Retrieve → Feedback → Decay
- 管理員可 approve / reject 記憶

#### Data Sources（`/system/data-sources`）

- System MCP 管理 — 每個 MCP 定義了 Agent 可以呼叫的外部 API
- 可編輯 endpoint URL、input schema、HTTP method
- Sample Fetch 測試功能

**MCP v3 — 三層資料架構：**

Agent 透過三個層級的 MCP 漸進式深入調查，從全廠概覽到單一參數深潛：

| Layer | MCP | 說明 |
|-------|-----|------|
| **L1 Summary** | `get_process_summary` | 聚合統計（OOC rates、per-tool breakdown、recent OOC）。MongoDB aggregation pipeline，毫秒回應。適合全廠掃描。 |
| **L2 Investigation** | `get_process_info` | 範圍調查。`objectName` 參數篩選 SPC/DC/APC/RECIPE，回應扁平化，回傳 pure data（chart DSL 由 Backend ChartMiddleware 自動生成）。**一次呼叫取代過去 8 次呼叫。** |
| **L3 Deep Dive** | `query_object_timeseries` | 單一參數深度時序 + 3σ OOC 標記 |
| 輔助 | `list_tools` | 廠內機台清單 |
| 輔助 | `get_simulation_status` | 模擬器系統狀態 |

**已退役**：`get_process_events`（被 L2 取代）、`get_object_info`（不再需要）

#### Event Registry（`/system/event-registry`）

- 事件類型登錄（SPC_OOC、RECIPE_CHANGE 等）
- NATS event bus 監控

---

## 4. AI Agent 技術細節

### 4.1 雙版本 Orchestrator

| 版本 | 架構 | 狀態 |
|------|------|------|
| **v1** | 單檔 monolith (~98KB)，6-stage pipeline | Production 預設，穩定 |
| **v2** | LangGraph StateGraph，模組化 nodes | Feature flag `?engine=v2`，驗證中 |

v2 的 LangGraph 架構：

```
load_context → llm_call → tool_execute → synthesis → self_critique → memory_lifecycle
                 ↑              │
                 └── loop ──────┘  (多輪工具呼叫)
```

### 4.2 Context Engineering

Agent 的 System Prompt 由 Context Loader 組裝：

1. **Soul Prompt** (~32KB) — 行為鐵律（§1.1~§1.16），定義 Agent 的推理原則
2. **MCP Catalog** — 從 DB 動態載入所有 active MCPs 的定義
3. **User Preference** — 個人偏好（語言、回覆風格）
4. **RAG Memory** — pgvector cosine + 關鍵字混合檢索相關經驗
5. **Session History** — 滑動視窗（最近 3 輪原文 + 舊的 LLM 摘要）

### 4.3 Tool Dispatcher

Agent 呼叫工具的統一入口，支援：

- `execute_skill` — 執行 Diagnostic Rule（sandbox Python）
- `execute_analysis` — 執行 Agent 即時生成的分析程式碼
- `execute_mcp` — 呼叫 System MCP（轉發到 OntologySimulator API）
- 參數正規化：`object_name/object_id` → `toolID/lotID` 自動轉換
- `since` 時間窗：`"7d"` → ISO8601 start_time 轉換
- 委派 ChartMiddleware 自動從 output_schema type 生成 chart DSL

**ChartMiddleware（chart_middleware.py）**：Registry-based 圖表自動生成中間層。LLM code 只需在 outputs 放 raw data + 在 output_schema 宣告 type（`spc_chart`, `line_chart`, `bar_chart`, `scatter_chart`, `multi_line_chart`），ChartMiddleware 自動產生 chart DSL。Simulator 不再回傳 `_charts`，所有 chart 生成統一在 Backend 處理。可擴充：`ChartMiddleware.register("heatmap", build_heatmap)`。

**MCP v3 效率提升**：`get_process_info` + `objectName=SPC` 一次呼叫取得 pure SPC data，Backend ChartMiddleware 自動產生 5 種 SPC chart DSL，取代過去 Agent 需要 8 次獨立 MCP 呼叫的流程。

### 4.4 AIOps Report Contract

Agent 與 Frontend 之間的共用語言（定義在 aiops-contract）：

```typescript
interface AIOpsReportContract {
  $schema: "aiops-report/v1"
  summary: string                    // 給人類讀的結論
  evidence_chain: EvidenceItem[]     // 每個工具呼叫的發現
  visualization: VisualizationItem[] // Vega-Lite 圖表
  suggested_actions: SuggestedAction[] // 建議動作按鈕
}
```

所有圖表透過 `contract.visualization` 在中央 Analysis Panel 渲染，Copilot 只顯示文字。

---

## 5. OntologySimulator（製程模擬器）

### 5.1 為什麼需要模擬器？

- 開發和 Demo 不需要連接真實 FAB 資料庫
- 與 production ontology **完全相同的 API 介面** — 切換只需改 `endpoint_url`
- 模擬真實的 OOC 事件、PM 週期、APC drift 等情境

### 5.2 模擬規模

- **99,999 個 Lot**（批次），10 個 Step（製程站點），10 台機台
- **6 種物件類型**：DC (30 sensors)、SPC (5 charts)、APC (20 params, active/passive)、RECIPE (20 params, versioned)、FDC (rule-based classification)、EC (8 constants, drift + PM recal)
- **OOC 機率 20%**，APC 每 step drift ±5% with **50% self-correction** on active params
- **Recipe 10% 進版** per process (key params ±offset)
- **DC sensor exponential drift** (slow baseline shift, PM reset)
- **NATS** 即時發布 OOC 事件 → Backend Auto-Patrol 訂閱
- 每次 process 產生 **1 event + 6 snapshots** (DC/SPC/APC/RECIPE/FDC/EC)

### 5.2.1 物件行為模型

| 物件 | 行為 | Pattern 預期 |
|------|------|-------------|
| **APC** | 5 active params (50% 修正) + 15 passive params (自由漂移) + derived metrics (model_r2, stability) | 鋸齒狀 trend（漂移→修正→再漂移） |
| **Recipe** | 10% 機率 version bump, 調整 etch_time_s/source_power/bias_power ±3~5% | Step function pattern（多數平穩，偶爾跳） |
| **DC** | Exponential drift (0.98 decay + gaussian noise), PM 後 reset to 0 | Slow wandering baseline + periodic reset |
| **SPC** | 監控 5 DC sensors, UCL/LCL hardcoded, OOC = ANY chart breach | ~20% OOC rate across all charts |
| **FDC** | Rule-based: SPC OOC + DC drift → FAULT; APC model degrading → WARNING | NORMAL > WARNING > FAULT distribution |
| **EC** | 8 constants, 0.1%/process micro-drift, PM 後 recalibrate to nominal ± noise | Slow linear drift, periodic PM reset |

### 5.3 API 概覽（4 個 System MCP）

| MCP | Endpoint | 說明 |
|-----|----------|------|
| `get_process_summary` | `/process/summary` | L1 聚合統計（OOC rates, per-tool breakdown） |
| `get_process_info` | `/process/info` | L2 範圍調查（6 種物件 nested，limit up to 500） |
| `list_tools` | `/tools` | 機台清單 + 狀態 |
| `get_simulation_status` | `/status` | 系統狀態快照 |

**已停用 MCP**：`query_object_timeseries` (endpoint 保留但從 LLM catalog 移除)

---

## 6. 部署架構 (DevOps)

### 6.1 Infrastructure

| Component | Spec |
|-----------|------|
| Server | AWS EC2 (單機) |
| OS | Ubuntu 24.04 |
| Domain | aiops-gill.com |
| SSL | Let's Encrypt (auto-renew) |
| Reverse Proxy | Nginx |
| Process Manager | systemd (3 services) |
| Database | PostgreSQL 16 + pgvector |
| NoSQL | MongoDB |
| Message Bus | NATS (optional) |
| Python | 3.11 |
| Node.js | 20 |

### 6.2 Service Map

| systemd Service | Process | Port | Health Check |
|-----------------|---------|------|-------------|
| `aiops-app` | Next.js standalone | 8000 | `GET /` |
| `fastapi-backend` | FastAPI (2 workers) | 8001 | `GET /health` |
| `ontology-simulator` | FastAPI + uvicorn | 8012 | `GET /api/v1/status` |

### 6.3 Nginx Routing

```
/              → 8000 (aiops-app, Next.js)
/api/v1/       → 8001 (fastapi backend, 直接)
/health        → 8001
/docs          → 8001 (Swagger UI)
/simulator/    → static files (Simulator Next.js export)
/simulator-api/ → 8012 (Simulator REST API)
/ws            → 8000 (WebSocket via Next.js)
```

### 6.4 Deploy 流程

**日常更新：**

```bash
# 方法 1: GitHub Actions (推薦)
# 到 repo → Actions → Deploy to Production → Run workflow

# 方法 2: SSH 手動
ssh -i ai-ops-key.pem ubuntu@aiops-gill.com
cd /opt/aiops && bash deploy/update.sh
```

**`deploy/update.sh` 做的事：**
1. `git pull` 拉最新 code
2. `pip install` 更新 Python 依賴
3. `alembic upgrade head` 跑 DB migration
4. `npm ci && npm run build` 建置 Next.js (standalone)
5. `systemctl restart` 重啟三個服務
6. 更新 nginx config
7. Health check 三個服務

**GitHub Actions Secrets（需設定）：**
- `EC2_HOST` — EC2 IP 或 domain
- `EC2_SSH_KEY` — SSH private key

### 6.5 檔案位置 (EC2)

```
/opt/aiops/                          ← Git repo root
├── fastapi_backend_service/
│   └── .env                         ← Backend 環境變數（DB, API keys）
├── aiops-app/
│   └── .env.local                   ← Frontend 環境變數
├── ontology_simulator/
│   └── .env                         ← Simulator 環境變數
├── venv_backend/                    ← Python venv (backend)
├── venv_ontology/                   ← Python venv (simulator)
├── deploy/
│   ├── update.sh                    ← Deploy script
│   ├── aiops-app.service            ← systemd unit
│   ├── fastapi-backend.service
│   ├── ontology-simulator.service
│   └── nginx.conf                   ← Nginx template
└── .nginx_domain                    ← Domain name for nginx
```

### 6.6 Database

**PostgreSQL (Backend)**

關鍵 tables：
- `skill_definitions` — Diagnostic Rules + Auto-Patrol Skills
- `mcp_definitions` — System MCP 定義
- `auto_patrols` — 巡檢排程
- `alarms` — 告警
- `agent_experience_memory` — AI 長期記憶 (含 pgvector embedding)
- `agent_sessions` — 對話 session（含滑動視窗摘要）
- `users` — 使用者帳號

> **Note (2026-04-09)：** `skill_authoring_sessions` table 已移除（見 §3.2 Inline Clarification）。

**MongoDB (Simulator)**

Collections：`lots`, `tools`, `events`, `object_snapshots`

### 6.7 Monitoring & Troubleshooting

```bash
# 查看服務狀態
sudo systemctl status aiops-app fastapi-backend ontology-simulator

# 查看 logs
sudo journalctl -u fastapi-backend -f        # backend 即時 log
sudo journalctl -u aiops-app -f              # frontend 即時 log
sudo journalctl -u ontology-simulator -f     # simulator 即時 log

# Health checks
curl http://127.0.0.1:8000                   # frontend
curl http://127.0.0.1:8001/health            # backend
curl http://127.0.0.1:8012/api/v1/status     # simulator

# DB 直接查詢
sudo -u postgres psql -d aiops_db
```

---

## 7. 已知限制與未來規劃

### 7.1 現有限制

| 項目 | 說明 |
|------|------|
| **單機部署** | 目前跑在單一 EC2，無 HA / auto-scaling |
| **Agent v2 未完全遷移** | LangGraph v2 已實作但 v1 仍是 production 預設 |
| **HITL 尚未實作** | Agent 無法在工具呼叫前暫停等待使用者確認 |
| **aiops-contract 在 monorepo** | 理想上應該是獨立 npm/pip package |
| **Simulator 取代真實 ontology** | Production 連的是模擬器，非真實 FAB DB |
| **bge-m3 需要 Ollama** | Memory embedding 依賴本地 Ollama 服務 |

### 7.2 建議的下一步

| Priority | 項目 | 說明 |
|----------|------|------|
| **P0** | 接真實 FAB 資料源 | 把 System MCP 的 endpoint_url 指向真實 ontology API |
| **P1** | Agent v2 切為預設 | 觀察穩定後移除 v1 orchestrator |
| **P1** | HITL (Human-in-the-loop) | LangGraph `interrupt()` 實作 |
| **P2** | Agent 拆為獨立微服務 | 從 backend 拆出 aiops-agent（SPEC 已標出邊界） |
| **P2** | Docker Compose | 取代手動 systemd 部署 |
| **P3** | 多廠區支援 | 每個 FAB 獨立 ontology + 共用 Agent |
| **P3** | Kubernetes | HA + auto-scaling |

---

## 8. Repo 結構 & 文件索引

```
aiops-platform/                       ← GitHub: gillggx/aiops-platform
├── README.md                         ← 2.0 總覽 + Quick Start
├── aiops-app/SPEC.md                 ← Frontend 技術規格
├── fastapi_backend_service/SPEC.md   ← Backend 技術規格
├── ontology_simulator/SPEC.md        ← Simulator 技術規格
├── aiops-contract/                   ← 共用型別定義 (TS + Python)
├── deploy/                           ← 部署相關（systemd, nginx, scripts）
├── docs/history/                     ← 歷史文件歸檔（v1~v21 PRD/specs）
└── .github/workflows/deploy.yml      ← GitHub Actions deploy
```

每個 project 的 `SPEC.md` 包含完整的：模組說明、API 列表、資料模型、技術棧。

---

## 9. 關鍵帳號與 Secrets

| 項目 | 位置 | 說明 |
|------|------|------|
| EC2 SSH Key | `~/Desktop/ai-ops-key.pem` | ubuntu@aiops-gill.com |
| Anthropic API Key | EC2 `/opt/aiops/fastapi_backend_service/.env` | Claude LLM |
| PostgreSQL | EC2 local | `aiops:***@localhost:5432/aiops_db` |
| MongoDB | EC2 local | `localhost:27017/ontology_simulator` |
| GitHub Secrets | Repo Settings → Actions | `EC2_HOST`, `EC2_SSH_KEY` |
| INTERNAL_API_TOKEN | Backend `.env` + aiops-app `.env.local` | 前後端共用 token |
| Domain SSL | Let's Encrypt auto-renew | aiops-gill.com |

---

*此文件由 Gill 與 Claude 協作完成。*
*如有問題請聯繫 Gill 或查閱各 project 的 SPEC.md。*
