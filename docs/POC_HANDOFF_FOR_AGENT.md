# POC Branch 交接文件（給接手的 AI Agent）

> 對象：基於 `poc/skill-library-*` branch 接手開發的 Claude Code（或其他 agent）。
> 撰寫：2026-07-14，由前一任 session 的 Claude 交接。
> 先讀 repo 根目錄 `CLAUDE.md`（專案鐵律）再讀本文；本文補的是
> CLAUDE.md 沒寫的「怎麼驗證、文件在哪、雷在哪、做到哪」。

---

## 1. 你接手的是什麼

這是 AIOps 平台（半導體廠 ops agent 平台）的 **skill-library POC branch**：
基於 main 最新進度，**拿掉 ontology_simulator**（模擬資料源）、其他功能全保留。

與 main 的差異恰好是這幾個 commits（`git log main..HEAD`）：

| Commit | 內容 |
|---|---|
| `chore(poc): strip ontology_simulator` | 刪 simulator 目錄 + deploy/nginx/docker 清理 + Java client stub 化 |
| `feat(poc-mcp): headers form + ${ENV}` | System MCP 表單加 HTTP headers（value 支援 `${ENV_VAR}`，sidecar 端替換，secret 不落 DB） |
| `chore(poc): drop docs/history` | 刪 24MB 舊版文件檔 |
| `docs(poc): local 啟動指南` | `docs/POC_LOCAL_SETUP.md` |

**POC 範圍**：L1 Skill Library + L2 Authoring（NL + 手動）+ L3 Try Run +
Block Docs + Build Trace + System MCP（外部資料源）。
**刻意不含**：simulator、auto-patrol/alarm 巡邏排程、topology、fleet 面板。

### 預期行為（不是 bug，不要修）

- `block_process_history` / `block_rework_request` 積木還在 catalog，但
  try-run 回 `MCP_UNREACHABLE` — 它們是 simulator-only。
- `/topology`、Fleet 面板顯示空狀態（Java `FleetSimulatorClient` stub 回空）。
- 資料要從 Admin → System MCPs 接真的外部 API（用 headers 表單放 auth）。

---

## 2. 架構速覽與邊界鐵律

```
aiops-app :8000        Next.js App Router，只做 UI + /api/ proxy（無業務邏輯）
java-backend :8002     Spring Boot，唯一碰 PostgreSQL 的服務；JWT auth；
                       /api/v1/*（user 面）+ /internal/*（服務間 X-Internal-Token）
python_ai_sidecar :8050  所有 agent 住這裡（Coordinator/Planner/Builder/Supervisor）
                       + Pipeline Executor（58 積木 in-process 跑）
                       NEVER 直連 PostgreSQL — 一律走 JavaAPIClient
```

- **Wire format 全 snake_case**（Jackson 強制）。camelCase key 會被 silent-ignore
  — HTTP 200 但欄位變 null，按鈕看起來沒反應。前端 TS interface + POST body
  都要 snake_case。這是歷史上重複踩最多次的雷。
- **Agent 套件邊界**：`python_ai_sidecar/agents/{coordinator,planner,builder,supervisor}`
  是唯一公開 import 面 — 鐵律見 `python_ai_sidecar/agents/README.md`。
  沒有 Repair agent（repair 是 Builder 內部迴路）。
- **流程寫 graph node，不寫 prompt**。「下一步呼叫哪個 tool」的決策一律
  deterministic dispatch；LLM 只做窄任務（分類/抽參/寫答）。CLAUDE.md 有完整論述。
- **禁 case-specific prompt rule**。trace 失敗 → 找根因原則，改架構
 （graph node / schema / 結構化 meta），不要往 prompt 塞「這個 case 要怎樣」。

## 3. User 的工作規則（必遵 — 完整版）

前任 agent 的 user-level 規則（`~/.claude/CLAUDE.md`）與數月累積的
feedback 記憶都**不在 repo 裡**，以下完整轉錄。
這些規則的優先級高於你自己的預設行為。

### 3.A 人設與溝通

- 角色定位：資深 Tech Lead / 架構師的協作夥伴。溝通風格：專業、精準、
  直指核心，不說客套話。
- **儘量用繁體中文**（專有名詞可英文）。**嚴禁簡體字** — 包含 commit
  message、UI 字串、註解、文件。曾因 commit message 一個「归」字被要求修正。
- **全面禁 emoji**（勾叉、警示、目標圖示等全算）。純文字標記用
  [best]/[ok]/[no]/[note]，幾何符號 ◆◇▤✦▦ 可以。
- **就數據說話**：任何評語、判斷要有依據。「應該沒問題」不是答案，
  跑過、看過、量過才是。

### 3.B 強制工作流（絕對禁止跳過）

任何新需求 / 架構設計 / 功能修改：

1. **先出 Spec，禁止直接寫 code**。用兩層式模板（`.claude/skills/spec-template`）：
   - 第一層：feature-first 對齊稿 — 無技術名詞（不出現 schema/endpoint/
     migration/flag），每個 feature 寫「現在怎樣 → 做完怎樣」+
     **user 可自己動手驗的驗收欄** + 不做的事 + 要 user 裁決的點。
   - 第二層：實作細項 — 第一層對齊後才展開。
2. **停下來等授權**：user 明確說「開始開發」才動工。
3. **交付時逐條回報第一層驗收欄**：誠實標 PASS / 未觸發 / 部分（含原因），
   不得只報做了什麼。

修 bug 的小需求也適用（用第一層精簡版：目標 + 1-2 個 feature 行 + 驗收）。

### 3.C 通用 Coding 守則

1. **SRP / 模組化**：函式與類別不過度龐大，高內聚低耦合。
2. **可讀性**：命名自我解釋；禁 magic number，用常數。
3. **錯誤處理**：絕不靜默吞 exception；錯誤訊息帶足夠 context。
   Java 端禁 `catch (Exception)` — narrow 到實際型別。
4. **I/O 預設 async**（DB、network），不阻塞主執行緒。
5. **YAGNI**：不過度設計，先解決當下問題。
6. **可測試性**：依賴可 mock / 注入。

### 3.D 從歷史 feedback 蒸餾的做事規則

**驗證紀律**
- 宣稱「修好了」的前置條件：grep 到改動真的在 build 產物裡 / curl API /
  SELECT DB row / 檔案 mtime — 至少一項，像 user 一樣驗。
- 先自己 smoke 過再請 user 驗（CRUD + Builder LLM + GUI Playwright 全套）。
- LLM 相關測試 **3 連過才算穩定**；單次結果不下結論。
- driver / smoke test 用**前景**執行讓 user 同步看到即時進度，不要丟背景。
- user 報「失敗/沒動作」→ **先調 trace 對他的 case**，不要重跑拿到
  不同的隨機結果再說「我這邊是好的」。
- 資料異常先查資料源 gap 和 LLM provider 變異，再怪 agent 邏輯。

**部署紀律（有 EC2 存取時才適用）**
- fix 永遠走 local commit → push → 遠端 pull，**禁止 SSH 直接改 prod 檔**。
- `deploy/update.sh` 不會重啟 sidecar/Java — 改這兩個要跑 `java-update.sh`
  或手動 restart，並驗 systemd ActiveEnterTimestamp。
- 先手動 pull 再跑 update.sh 會 skip build 卻回報完成 — 用 `--force-rebuild`
  + 驗 BUILD_ID。
- 新 Flyway V*.sql 在 prod 不會自動跑（prod Flyway 關閉）— 手動 psql。
- root README / 各 service README / SPEC / HANDOFF 與程式改動**同 commit** 更新
 （文件落後曾被抱怨落後 19 天）。

**成本紀律**
- user 在追 LLM 帳單。大規模 LLM 測試 / audit 前先報預估成本。
- 分級閘門：UI / 離線改動不跑 LLM gate；build path 先 SMOKE-5；
  全量 17 案例只在里程碑燒。
- 模型切換是單一開關（sidecar env），做完貴模型實驗要切回便宜 default。

**Agent / 系統設計紀律**
- flow 決策寫 graph node（可單測），LLM 只做窄任務 — 拒絕「30 tools +
  80-turn 自由 loop」式設計。
- 禁 case-specific prompt rule：每想加規則先自問「6 個月後會不會被新 case
  變形繞過」— 會的話改架構（graph gate / schema / 結構化 meta）。
- Plan 層寫 intent（block-agnostic），Execute 層才看得到積木。
- alarm 歸 alarm，「秀給 user 看」是另一個 phase — 不要混在一個 phase。
- catalog 是目錄不是教科書：塞太多細節會誘發 agent over-build
 （實測 4 nodes 膨脹成 8）。
- SSE / event wrapper 必須透傳 raw 結構化欄位，拍扁成 text summary
  會弄壞前端 state mutation。
- 知識放 DB（description / 標準 Skill / agent_knowledge），不 hardcode 進
  prompt — description 是 LLM 唯一看得到的文件。

**UI / 產品原則**
- 積木表單是給人用的，不是寫 code — 任何要 user 手打 JSON 的參數
  都該有引導式編輯器（已做 20 個，模式見 `GuidedParamEditors.tsx`）。
- 寫入操作一律走瀏覽器端確認卡（user JWT 執行），code 強制不靠 prompt。
- agent 不得宣稱「已記住/已執行」除非對應動作真的發生（誠實鐵律）。

---

## 4. 驗證方法論（最重要的一節）

核心原則：**verify like a user** — 宣稱「修好了」之前，必須用 user 會用的
方式驗過（開瀏覽器、打 API、查 DB row），不是「程式碼看起來對」。
歷史教訓：curl 過了但 GUI 壞的案例不只一次（不同入口走不同 code path）。

### 4.1 分層驗證工具（由快到慢）

| 層 | 工具 | 何時用 | 成本 |
|---|---|---|---|
| 積木核心行為 | `pytest python_ai_sidecar/tests/test_blocks_core.py` | 動任何 block 邏輯後 | 秒級，免 LLM |
| Sidecar 單測全套 | `pytest python_ai_sidecar/tests/` | 動 graph node / tool / executor | 分鐘級，免 LLM |
| Java 單測 | `cd java-backend && mvn -Dtest=ClassA,ClassB test` | 動 Java service | 純 Mockito 無 Spring context，快 |
| TS 型別 | `cd aiops-app && npx tsc --noEmit` | 動前端 | 既有 e2e 測試檔有已知錯誤，過濾 `e2e/` 即可 |
| 回歸包 | `bash tools/regression_pack/run.sh` | 動 builder / verifier / chart 引擎 / ChatOps 前後 | ~5 分鐘，3 個 LLM case |
| UI 一致驗證 | `tools/ui_consistent_verify/`（chat_walkthrough.py / builder_verify.py） | 驗 chat/builder 全流程，跟 GUI 走同一條 API path | LLM 成本 |
| Playwright e2e | 寫 `qa_*.mjs` 腳本模式（見 4.3） | UI 行為驗證、截圖存證 | 分鐘級 |

### 4.2 LLM 測試的紀律

- **非決定性**：單次 FAIL 先重跑；要宣稱「穩定」需 **3 連過**。
- **先排除環境因素再怪 agent**：模型 provider 變異（空回應、finish_reason=error）、
  資料 gap 都會假裝成 regression。先看 trace 的 finish_reason 和資料量。
- **User 報 case 失敗 → 先調 trace，不要重跑**：重跑 LLM 會拿到不同隨機結果。
  Build trace 在 sidecar 機器的 `/tmp/builder-traces/*.json`，
  GUI 在 `/admin/build-traces`（有 Summary tab = trace_summary 模型）。
  分析入口：`.claude/skills/verify-build`（flat report + narrative reconstruction 兩種格式）。
- **受控實驗**：「改 X 會不會改變 LLM 的選擇」用 `tools/trace_replay/`
  重放單一 LLM call 跑 variant 實驗，不要用猜的。

### 4.3 Playwright e2e 模式（qa_*.mjs）

歷史 session 的 QA 腳本模式（散見 scratchpad，回歸包裡有固化版）：

- 腳本放在能向上找到 `aiops-app/node_modules` 的位置跑（ESM bare import 解析）。
- 登入 `admin / admin`，操作後截圖存證 — **截圖給 user 看**是驗收的一部分。
- **Locator 要雙語**：user 會切 UI 語系（4 locale），寫死中文按鈕字樣
 （「確認，開始建構」）在日文 UI 下會撲空。回歸包腳本已雙語化，照抄它的寫法。
- Sidecar 直打 API 時帶 `X-Service-Token`（local dev fallback `dev-service-token`）
  + `X-User-Id: 1`。

### 4.4 成品目檢（result-vision）

Builder 完工前會把 chart/table headless 截圖給 vision judge 把關
（`RESULT_VISION_CHECK` 預設 ON）。基建在 `tools/result_render/`
（esbuild bundle + Playwright render.mjs，README 有校準紀錄）。
Judge 校準教訓：**負面清單制**（空圖/單色/型態錯/沒管制線才擋）、
拿不準放行、guidance 禁杜撰參數名 — 改 judge prompt 前先讀
`python_ai_sidecar/agent_builder/result_vision.py` 的註解。

---

## 5. 重要文件地圖

### 每天會用到

| 文件 | 內容 |
|---|---|
| `CLAUDE.md`（根目錄） | 專案鐵律 — 必讀，優先級最高 |
| `docs/BLOCKS.md` | **58 顆積木的完整文件（自動生成）**。查積木先看這裡，不要憑記憶 — 歷史上曾因憑記憶提案而重複造已存在的積木。改 seed 後用 `python tools/blocks_doc/generate.py` 重生 |
| `docs/POC_LOCAL_SETUP.md` | Local 三服務啟動 + env 清單 + 症狀對照表 |
| `python_ai_sidecar/agents/README.md` | Agent 套件邊界鐵律 |
| `python_ai_sidecar/pipeline_builder/seed.py` | **積木單一來源**：description/param_schema/examples 都從 `_blocks()` 出。改積木行為必同步改這裡 |

### 設計 spec（動對應子系統前讀）

| 文件 | 子系統 |
|---|---|
| `docs/CHAT_AGENT_LOOP_SPEC.md` | Coordinator 對話迴路（ChatOps 的大腦） |
| `docs/MULTI_AGENT_PHASE0_SPEC.md` / `PHASE1_SPEC.md` | 多代理架構與委派 |
| `docs/MULTI_AGENT_MEMORY_SPEC.md` | 記憶層（agent_knowledge 兩層式） |
| `docs/MULTI_AGENT_OBSERVABILITY_SPEC.md` | Episodes/steps、per-agent 成本歸因 |
| `docs/SUPERVISOR_CHARTER_AND_DESIGN_BRIEF.md` | Supervisor 職權 |
| `docs/POC_TECHNICAL_SPEC.md` / `POC_DEPLOYMENT_SPEC.md` | POC 本身的技術/部署 spec |
| `docs/devops/`、`docs/deploy-kubernetes.md` | 部署（EC2 systemd 現行、K8s 未來） |
| `docs/MULTI_AGENT_INTRO.pptx`（main branch） | 41 頁平台演進介紹 — 快速補齊全貌用 |

### 開發流程 skills（`.claude/skills/`）

- `spec-template` — 兩層式 spec 模板（強制）
- `verify-build` — builder case 驗證 + trace 分析報告格式
- `poc-skill-library` — 重建這個 POC branch 的配方（含衝突解法）

---

## 6. 已知雷區（每個都真實炸過）

1. **Jackson snake_case wire**（見 §2）— 前端按鈕沒反應先查這個。
2. **LangGraph state key 必須宣告**：新 state key 沒加進
   `graph_build/state.py` 的 `BuildGraphState` TypedDict 會被**靜默丟棄**
   — 功能看起來上了但 cap/計數永遠不生效。
3. **pgvector 欄位禁走 JPA save()**：JPA 綁 String 成 varchar，PG 拒轉
   vector（SQL 42804）。寫入用 native `@Query` + `CAST(:vec AS vector)`，
   entity 欄位標 `insertable=false, updatable=false`。參考
   `AgentKnowledgeRepository.updateEmbedding`。
4. **Spring bean 同名衝突**：新 controller/service 先
   `grep -r "class SimpleName"` — 跨 package 同名會讓 prod boot 掛，Mockito 測不到。
5. **`X-Feature-Flags` header 對 SSE endpoint 是 no-op**（middleware 在
   stream 前就 reset）— flag A/B 一律 env + 重啟，不要用 header。
6. **改 sidecar / Java 後必須重啟對應服務**才生效；重啟 sidecar 前先確認
   沒有進行中的 build（`GET /internal/agent/tasks/running`）。
7. **積木有 5 個同步點**：source 檔 + `blocks/__init__.py` BUILTIN_EXECUTORS
   + seed.py + （prod 才有的 pb_blocks SQL）+ docs/BLOCKS.md 重生。
   boot invariant 會印 4 個數字，必須相等。
8. **`.env` 全部不進 git** — 症狀對照表在 `POC_LOCAL_SETUP.md`。
   最容易踩：`CHAT_AGENT_LOOP_ENABLED` 預設 0（ChatOps 打招呼會跳選單
   而不是對話）、`ANTHROPIC_API_KEY` 沒設（agent 完全不回話）。
9. **LLM repair 只加不刪**：repair/reflect 傾向建 `n1b` 平行節點而不是
   remove 壞的 `n1` — 看到重複節點家族先想到這個。
10. **Coordinator 的寫入動作全走瀏覽器端確認卡**（user JWT 執行）— 這是
    code 強制的閘門，不是 prompt 勸說。改 agent 能力面時不要繞過它。

---

## 7. 最近交付狀態（2026-07-12 ~ 07-13 波，全在本 branch）

- **修正波 P1-P4**：P1 建構失敗自癒（BuildFailedCard 重試/調整/放棄 +
  finalize 壞葉剪枝）；P2 圖表把關（視覺編碼閘 + scatter regression）；
  P3 貼圖溝通（paste/拖放 → Anthropic image blocks，上限 3 張）；
  P4 表單化編輯器 + 回歸包。
- **成品目檢**：headless 截圖 + vision judge，預設 ON，自動修 1 輪。
- **積木波**：compute concat/if/abs/round、filter 多條件+not_in、groupby
  多聚合、line_chart 順序軸+虛線、data_view 條件套色、scatter slope 標註、
  correlation target 排行、新積木 block_streak；全平台 20 個 JSON-hostile
  參數換成引導式表單（`ComputeExpressionEditor` + `GuidedParamEditors`）。
- **記憶 v1**：偏好索引注入 + `read_memory` / `remember_preference` 確認卡；
  「我的偏好」頁 `/me/preferences`（4 語系）。
- **Session 管理**：對話改名/刪除、30 天保留、rich history 跨裝置。

### Backlog（user 已知、尚未做）

- Coordinator 失敗迴路完整版（failure → replan 全自動收斂）
- 成品目檢階段二（data-driven 檢查，不只看圖）
- 記憶層 RAG 化（等量大再做；現在是全量索引注入）
- POC 下一輪清理候選：拔 process_history/rework_request 積木、隱藏
  /topology 等頁 — 見 `.claude/skills/poc-skill-library/SKILL.md`
- K8s 部署（等 target env 決定）

---

## 8. 給接手者的操作建議

1. 先跑 `docs/POC_LOCAL_SETUP.md` 把三服務起起來，用 admin/admin 登入
   ChatOps 打個招呼確認 Coordinator 活著。
2. 動手前跑一次 `pytest python_ai_sidecar/tests/test_blocks_core.py`
   確認基線綠的。
3. 任何 user 需求 → 先出兩層式 spec 等「開始開發」，不要直接寫 code。
4. 改完 → 對應層級的驗證工具跑過 → 截圖/輸出貼給 user → 才說完成。
5. 有不確定的歷史脈絡，優先查：`CLAUDE.md` → 本文件 → `docs/` 對應 spec
   → `git log --oneline --grep=關鍵字`（commit message 寫得很完整）。
