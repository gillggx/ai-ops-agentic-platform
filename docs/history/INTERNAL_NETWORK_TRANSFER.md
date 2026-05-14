# AIOps Platform — Internal-Network / Air-Gapped Transfer Audit

**Last updated**: 2026-05-09
**Phase**: 4 (project-restructure / internal-network audit)
**Scope**: 4 active services + simulator + frontend, all built from this repo

> 用途：把整個 AIOps 平台搬到內網 / air-gapped EC2 / on-prem
> Kubernetes 之前，這份文件是唯一的 transfer checklist。每加一個新 dep
> 或新 endpoint 都要回頭更新這份。

## TL;DR

| Item | 內網可用？ | 行動 |
|---|---|---|
| Java build (gradle + Maven Central) | ❌ | warm `~/.gradle/caches`，內網 Nexus mirror |
| Python build (pip + PyPI) | ❌ | `pip download` 到 `/opt/wheels`，內網 devpi/pip-mirror |
| Frontend build (npm) | ❌ | warm `~/.npm/_cacache`，內網 Verdaccio |
| **Anthropic API (runtime)** | ❌ | **無代理 = chat / builder 不可用**；其他服務不受影響 |
| mem0 cloud (sidecar) | ⚠️ | 沒設 `MEM0_API_KEY` → silent no-op，無 hard dep |
| Postgres / Redis / MongoDB | ✅ | apt 內網 mirror 即可 |
| Java OIDC（Azure AD） | ⚠️ | 需要 OIDC 端點可達；可改 local credential mode |
| Google Fonts (frontend CSS) | ⚠️ | UI 仍可用（fallback system fonts），詳見 §3 |
| Vega-Lite schema URI | ✅ | 純 metadata，渲染器不真的 fetch |

## 1. Build-time external resources

每個服務都要在有外網的環境跑一次 [`scripts/warm-build-caches.sh`](../scripts/warm-build-caches.sh)
把所有 dep 抓下來。下面表列所有來源 + 內網替代方案。

### 1.1 Java（java-backend + java-scheduler）

| Source | What | 內網方案 |
|---|---|---|
| `repo.maven.apache.org` (Maven Central) | Spring Boot 3.5.0、Hibernate、Lombok、PostgreSQL JDBC、pgvector、Lettuce / Redis client、jackson、auth0 jwt 等 ~60 個 jars | 內網 Nexus / Artifactory proxy（指向 Maven Central） |
| `plugins.gradle.org` | Spring Boot plugin、io.spring.dependency-management plugin | 同上 — 在 `settings.gradle.kts` 加 `pluginManagement.repositories` 指向內網 |
| `services.gradle.org` | gradle-8.14.4 distribution | 一次性 vendored，下載 zip 後改 `gradle/wrapper/gradle-wrapper.properties` 的 `distributionUrl` 指向內網 HTTP 路徑 |

**Versions**（截至 2026-05-09）：
- Java 21（Temurin） · Spring Boot 3.5.0 · Gradle 8.14.4
- 完整 BOM：`./gradlew :java-backend:dependencies`、`./gradlew :java-scheduler:dependencies`

### 1.2 Python sidecar（python_ai_sidecar）

| 主要 deps | 來源 | Notes |
|---|---|---|
| fastapi 0.115.4, uvicorn 0.32.0, pydantic 2.9.2 | PyPI | 標準 |
| anthropic ≥0.42.0 | PyPI | runtime 連 api.anthropic.com — **此 dep 仍要打包，runtime 才是 air-gap 障礙** |
| pandas 2.2.3, numpy 2.1.3, scipy 1.14.1 | PyPI | 大型 wheel，pre-download 確認 manylinux2014 wheel 可用 |
| langchain-core ≥0.3.0, langgraph ≥0.2.0 | PyPI | chat orchestrator 必需 |
| mem0ai ≥0.1.29 | PyPI | runtime fail-open（沒 key 就 noop） |
| sqlalchemy 2.0.36 | PyPI | transitive only，sidecar 不開 DB session |
| tiktoken ≥0.7.0 | PyPI | best-effort，缺也 fallback CJK heuristic |
| croniter ≥2.0,<4.0 | PyPI | Phase 9-B 加的 |

完整列表見 [`python_ai_sidecar/requirements.txt`](../python_ai_sidecar/requirements.txt)。

### 1.3 Python simulator（ontology_simulator）

| deps | 來源 |
|---|---|
| fastapi, uvicorn, motor (Mongo async), pymongo, python-dotenv, nats-py | PyPI |

完整列表見 [`ontology_simulator/requirements.txt`](../ontology_simulator/requirements.txt)。

### 1.4 Frontend（aiops-app）

| 主要 deps | 來源 | Notes |
|---|---|---|
| next 15.2.4, react 19.0.0, next-auth 5.0.0-beta.31 | npm | 標準 |
| @anthropic-ai/sdk 0.80.0 | npm | runtime 不會被 frontend 直接呼叫（API call 透過 Java） |
| @xyflow/react, @dagrejs/dagre | npm | Pipeline Builder canvas |
| @visx/{brush,scale,group,axis} 3.12.0 | npm | Phase 9 的 Topology Trace timeline |
| react-markdown, remark-gfm | npm | chat panel rendering |
| react-resizable-panels | npm | layout |

`aiops-app/.npmrc` 設了 `legacy-peer-deps=true` — 在 React 19 + visx 3.12 peerDep ^18 衝突的解；npm-mirror 不影響。

### 1.5 OS-level

| 項目 | 來源 | 內網方案 |
|---|---|---|
| `python3.11` | deadsnakes PPA | 內網 apt mirror |
| `temurin-21-jdk` | adoptium.net | 內網 apt mirror |
| `mongodb-org-7.0` | mongodb.org | 內網 apt mirror |
| `redis-server` | Ubuntu universe | 內網 apt mirror（標準包） |
| `nodejs` (20.x) | NodeSource | 內網 apt mirror |
| `postgresql-contrib`, `nginx`, `certbot` | Ubuntu main | 內網 apt mirror（標準包） |

## 2. Runtime external resources

> 這些是 build 完跑起來會主動連外的服務 — 內網要嘛裝代理，要嘛接受功能下線。

| 服務 | 用途 | 環境變數 | Air-gap 行為 |
|---|---|---|---|
| **api.anthropic.com** | sidecar `agent_orchestrator_v2` + `agent_builder` LLM 呼叫 | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS` | **chat panel + Glass Box builder + Block Advisor 全部不能用**；其餘 service（Java、simulator、Pipeline Executor、auto-patrol scheduler 跑既有 pipeline）不受影響 |
| api.mem0.ai | sidecar 語意記憶（agent 會記偏好 / 失敗模式） | `MEM0_API_KEY`（沒設 = silent no-op） | 沒設就跳過寫；不擋 boot |
| login.microsoftonline.com（OIDC） | java-backend OIDC SSO（Azure AD） | `OIDC_ISSUER` / `OIDC_CLIENT_ID/SECRET` / `AUTH_MODE` | 設 `AUTH_MODE=local` 改用 local credential（admin/gill/itadmin_test 等帳號），不需要外部 OIDC |
| fonts.googleapis.com | aiops-app 的 4 個頁面用 Google Fonts CSS（Inter Tight + JetBrains Mono / IBM Plex Mono） | n/a — hardcode | UI **仍可用**（瀏覽器 fallback 到 system font），但字型會跟 prod 不一樣。內網要修就把 `<link>` 換成 self-hosted CSS，或改 `next/font/google` 改成 `next/font/local` 後 vendor 字型檔 |
| Anthropic Vega-Lite schema URI（`https://vega.github.io/schema/vega-lite/v5.json`） | chart spec 內 `$schema` 欄位 | n/a | 純 metadata，渲染時不會 fetch — air-gap **無影響** |
| simulator NATS / WebSocket（`/ws`） | simulator → frontend live event broadcast | local only | 不對外，無關 |

## 3. Hardcoded URL audit results（2026-05-09）

跑了 grep 結果：

✅ **0 hardcoded long-string secrets**（API keys / tokens / passwords 全部來自 env 變數）

⚠️ **4 個 Google Fonts CDN URL** in `aiops-app`：
- `aiops-app/src/app/alarms/[id]/page.tsx`
- `aiops-app/src/app/alarms/page.tsx`
- `aiops-app/src/components/fleet/FleetOverview.tsx`
- `aiops-app/src/components/fleet/eqp/EqpDetail.tsx`

每個都是 `<link rel="stylesheet" href="https://fonts.googleapis.com/...">` 模式。

**Decision (2026-05-09)**：暫不修。Air-gap 環境裡瀏覽器會 timeout 後 fallback 到系統字型，UI 仍可用 — 字型差異不阻擋功能。後續若要修：

```tsx
// 替換成 next/font/local：
import localFont from "next/font/local";
const interTight = localFont({ src: "./fonts/InterTight.woff2" });
// 然後 className 用 interTight.className，移除 <link>
```

✅ Microsoft OIDC URL 在 [`application.yml`](../java-backend/src/main/resources/application.yml) 跟 [`auth.ts`](../aiops-app/src/auth.ts) 都是 `${OIDC_ISSUER:default}` env-driven，內網改 env 即可。

## 4. Offline build runbook

需要的環境：
- 一台**有外網**的 build host（dev laptop 或 jenkins runner）
- 一台**內網 / air-gapped** 目標 host

### 4.1 在有外網的 host warm cache

```bash
cd /path/to/repo
bash scripts/warm-build-caches.sh
```

完成後會在 stdout 列出怎麼打包：

```bash
tar czf gradle-caches.tar.gz   -C $HOME .gradle/caches
tar czf npm-caches.tar.gz      -C $HOME .npm/_cacache
tar czf node-modules.tar.gz    aiops-app/node_modules
tar czf sidecar-wheels.tar.gz  -C /opt/wheels sidecar
tar czf simulator-wheels.tar.gz -C /opt/wheels simulator
```

### 4.2 把這 5 個 tar + repo zip 搬到內網 host

```bash
# 目標 host 解開
mkdir -p $HOME/.gradle && tar xzf gradle-caches.tar.gz -C $HOME/.gradle
mkdir -p $HOME/.npm   && tar xzf npm-caches.tar.gz -C $HOME/.npm
sudo mkdir -p /opt/wheels && sudo tar xzf sidecar-wheels.tar.gz -C /opt/wheels
sudo tar xzf simulator-wheels.tar.gz -C /opt/wheels

unzip aiops-platform.zip
cd aiops-platform
tar xzf ../node-modules.tar.gz -C aiops-app/
```

### 4.3 build with --offline

```bash
# Java
./gradlew :java-backend:bootJar :java-scheduler:bootJar --offline

# Frontend
cd aiops-app && npm ci --offline && npm run build && cd ..

# Sidecar
python3 -m venv /opt/aiops/venv_sidecar
/opt/aiops/venv_sidecar/bin/pip install --no-index --find-links /opt/wheels/sidecar \
    -r python_ai_sidecar/requirements.txt

# Simulator
python3 -m venv /opt/aiops/venv_ontology
/opt/aiops/venv_ontology/bin/pip install --no-index --find-links /opt/wheels/simulator \
    -r ontology_simulator/requirements.txt
```

然後 [`deploy/setup.sh`](../deploy/setup.sh) / [`deploy/java-update.sh`](../deploy/java-update.sh) /
[`deploy/update.sh`](../deploy/update.sh) 一樣可以跑（systemd 部分不需要外網）。

## 5. Per-PR transfer checklist（每個新 PR 跑一次）

```
□ 沒新增 hardcoded URL（除 localhost / 127.0.0.1 / *.example.com）
□ 沒新增 hardcoded long secret（用 ${ENV_VAR:fallback}）
□ 新 dep 加進對應的 requirements.txt / package.json / build.gradle.kts，pin 版本
□ 跑過一次 grep（同 §3）確認沒回退
□ 如果有新外部 runtime call（API URL）：在這份文件 §2 加一條
□ 如果有新外部 build dep：在 §1 對應子段加一條
```

## 6. 已知 / 待修

| 項目 | 狀態 | 備註 |
|---|---|---|
| Anthropic API 內網代理 | 📋 backlog | user 確認 2026-05-09：「先不用」— chat 在內網先停用 |
| Google Fonts vendor 化 | 📋 backlog | UI fallback OK；要 prod 字型一致再做 |
| 真實 air-gap build 驗證 | 📋 backlog | user 2026-05-09：「之後再驗」— spec 階段先做文件 |
| Maven plugin portal mirror 設定 | 📋 setup-time | 真實內網 setup 時加進 settings.gradle.kts |
