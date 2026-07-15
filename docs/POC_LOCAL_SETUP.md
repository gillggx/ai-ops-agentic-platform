# POC (skill-library branch) — Local 啟動指南

適用 branch：`poc/skill-library-*`（去 simulator 版）。
三個服務：aiops-app :8000（Next.js）、java-backend :8002（Spring Boot，唯一
碰 DB 的服務）、python_ai_sidecar :8050（Agents + Pipeline Executor）。
**沒有 simulator** — 資料來源要靠 System MCP 接外部 API（見最後一節）。

## 0. 前置需求

| 元件 | 版本 |
|---|---|
| Java (Temurin) | 17 |
| Maven | 3.9+ |
| Python | 3.11 |
| Node.js | 20.18 |
| PostgreSQL | 15+，需 `pgvector` extension |

## 1. Database

```bash
createdb aiops
psql -d aiops -c 'CREATE EXTENSION IF NOT EXISTS vector;'
# 帳密走 java-backend 預設 aiops/aiops，或自建後用 env 覆寫
```

Local 的 Flyway 是**開的**（`application.yml: flyway.enabled=true`），
java-backend 第一次啟動會自動跑完 `db/migration/V*.sql` 全部 schema。
（EC2 prod 是關的、要手動 psql — local 不用管這件事。）

## 2. java-backend（:8002）

```bash
cd java-backend
# 預設就會連 localhost:5432/aiops (aiops/aiops)；不同的話：
export DB_URL=jdbc:postgresql://localhost:5432/aiops DB_USER=aiops DB_PASSWORD=aiops
mvn spring-boot:run
```

`JAVA_INTERNAL_TOKEN` 不設會 fallback 到 `dev-internal-token`（local 可用；
prod 必設）。

## 3. python_ai_sidecar（:8050）

```bash
cd <repo root>
python3.11 -m venv venv_sidecar && source venv_sidecar/bin/activate
pip install -r python_ai_sidecar/requirements.txt
```

`python_ai_sidecar/.env`（.env 不進 git，clone 下來一定是空的）：

```bash
# ── 必設 ────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...          # 沒有它 agent 完全不會回話
CHAT_AGENT_LOOP_ENABLED=1             # 不設 = 舊版分類器路徑：
                                      # 打招呼會跳「要做什麼」選單而不是對話
# ── 建議 ────────────────────────────────────────────────
ANTHROPIC_MODEL=claude-haiku-4-5-20251001   # prod 同款（成本/延遲最佳）

# ── Prod parity flags（2026-07-15 抄自 prod 實際設定）────
# 這些 flag 在 code 全部預設 0/False — 不設的話 local 行為跟 prod 有
# 17 處差異。最有感的：ENABLE_AGENT_EPISODES 不開 → /agent-activity
# 頁永遠空白（agent 有跑但沒寫 episodes）。
ENABLE_AGENT_EPISODES=1        # /agent-activity 觀測頁的資料來源
ENABLE_MEMORY_WRITES=1         # 記憶層 W1-W3 fast-path 寫入
ENABLE_PLAN_KNOWLEDGE=1        # plan 層知識注入
ENABLE_EXECUTE_KNOWLEDGE=1     # execute 層知識注入
ENABLE_ATOMIC_ADD_CONNECT=1
ENABLE_AUTO_SIGNAL=1
ENABLE_AUTO_VERIFIER=1
ENABLE_CONSTRUCT_PARAM_DOC=1
ENABLE_INTERACTIVE_BRIEF=1
ENABLE_NEXT_MEMO=1
ENABLE_NO_DUPLICATE_NODE=1
ENABLE_ORPHAN_RESOLVE=1
ENABLE_RICH_CANVAS_SNAPSHOT=1
ENABLE_RICH_SCHEMA_VALUES=1
ENABLE_STRICT_PHASE_OUTPUT=1
ENABLE_STRICT_PHASE_VERIFY=1
PIPELINE_ONLY_MODE=1
# prod 刻意關著的（不要開）：ENABLE_GOAL_AWARE_MATCHING=0、
# ENABLE_PRESENTATION_LOOKAHEAD=0、ENABLE_LAYERED_PLAN_KNOWLEDGE 未設

# ── 有預設值，非 localhost 佈局才要改 ──────────────────
# JAVA_API_URL=http://localhost:8002
# JAVA_INTERNAL_TOKEN=dev-internal-token    # 要跟 java 端一致
# SERVICE_TOKEN=dev-service-token           # 要跟前端 SIDECAR_SERVICE_TOKEN 一致
```

啟動：

```bash
uvicorn python_ai_sidecar.main:app --host 127.0.0.1 --port 8050
```

## 4. aiops-app（:8000）

`aiops-app/.env.local`：

```bash
FASTAPI_BASE_URL=http://localhost:8002    # 名字是歷史遺留，指向 Java
SIDECAR_BASE_URL=http://localhost:8050
SIDECAR_SERVICE_TOKEN=dev-service-token   # 跟 sidecar SERVICE_TOKEN 一致
AGENT_BASE_URL=http://localhost:8050
AGENT_BUILD_BASE_URL=http://localhost:8050
```

```bash
cd aiops-app && npm install && npm run dev   # http://localhost:8000 需 -p 8000，next dev 預設 3000
```

註：`next dev` 預設 port 3000，要跟 prod 對齊用 `npm run dev -- -p 8000`。

登入：`admin / admin`（首次啟動 seed）。

## 5. 常見症狀對照

| 症狀 | 原因 | 修法 |
|---|---|---|
| ChatOps 打 hello 跳選單不對話 | `CHAT_AGENT_LOOP_ENABLED` 沒設（預設 0） | sidecar .env 設 1 後重啟 |
| 對話有跑但 `/agent-activity` 空白 | `ENABLE_AGENT_EPISODES` 沒設（預設 0），episodes 沒寫 | sidecar .env 設 1 後重啟；歷史對話不會回填 |
| Agent 完全沒回應 / 500 | `ANTHROPIC_API_KEY` 沒設 | 設 key |
| 前端按鈕沒反應但 HTTP 200 | POST body 用了 camelCase | Java wire 全 snake_case |
| `process_history` 積木回 `MCP_UNREACHABLE` | 本 branch 沒 simulator（預期行為） | 用 System MCP 接外部 API |
| pgvector 寫入 SQL 42804 | JPA 綁 varchar | 已知限制，見 CLAUDE.md pgvector 節 |

## 6. 外部資料源（取代 simulator）

Admin → System MCPs → 新增：Endpoint URL 填外部 API、
「HTTP Headers (optional)」填 auth（value 支援 `${ENV_VAR}`，例
`Bearer ${EXTERNAL_API_TOKEN}` — sidecar 發送時才從 .env 替換，secret
不落 DB）。對應的環境變數加進 `python_ai_sidecar/.env` 後重啟 sidecar。
