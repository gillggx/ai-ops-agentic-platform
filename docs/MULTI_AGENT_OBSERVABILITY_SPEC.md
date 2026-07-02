# Multi-Agent 下一階段 — Agent 行為觀測與 Supervisor 調校迴路

> Draft v1 · 2026-07-02。承接 Phase 0（已交付,A1-A10 全過）。
> **本階段取代原 Phase 1（業務監控）成為下一步** —— 業務監控平面
> （`MULTI_AGent_PHASE1_SPEC.md`）往後排;沒有 agent 觀測,Supervisor 是瞎的,
> 其他一切學習迴路都無料可用。
>
> **流程**:目的優先（目的 → 監測事項 → 記錄設計 → Supervisor 運作),
> 驗收條款（§9）與 spec 一起簽核。

---

## 1. 目的（為什麼要記錄 agent 行為）

| # | 目的 | 沒有它會怎樣 |
|---|---|---|
| O1 | **可歸因** — 出錯時知道是哪個 agent、哪一步、為什麼 | 只能人工讀整份 trace 猜 |
| O2 | **可調校** — Supervisor 據數據調每個 agent（prompt / 知識 / doc / budget） | 調校靠手感,改了不知有沒有效 |
| O3 | **可量化** — 每 agent 的品質 / 成本 / 效率有趨勢線 | 回歸偵測只能靠跑全套 SLASH-17 |
| O4 | **可學習** — 行為記錄蒸餾成 durable memory（接 AGENT_HARNESS_DESIGN 的 6 class） | 每次 build 從零開始 |

---

## 2. 監測事項（每個 agent 要記什麼）

### Planner — 核心問題:「plan 對不對?」
| 事項 | 訊號 |
|---|---|
| plan 提出 vs user 修改 | confirm gate 的 **edit diff**（最強的即時訊號,現在就拿得到） |
| replan | 次數 + 原因（judge deficit / user 要求 / 裁判 REPLAN(未來)） |
| 拆分品質 | plan 的 phase 數 vs 實際完成用的 phase 數（過度拆分 / fast-forward 合併） |
| （Phase 2+）語意裁判 | 每次 verdict（APPROVE/REVISE/REPLAN）+ 理由 |

### Builder — 核心問題:「執行卡在哪、為什麼?」
| 事項 | 訊號 |
|---|---|
| block 選擇 | matching 給了哪些選項 vs 實際選了哪個 |
| **param 猜錯→被拒→改對** | (block, param, 錯值, 對值) —— **doc 備忘的直接原料** |
| doc 失真 | inspect 發現實際欄位 ≠ doc 所述 (block, field) |
| verifier 拒絕 | 結構化理由（covers mismatch / orphan / leaf / judge reject） |
| 效率 | 每 phase round 數、stuck / 升級事件 |

### Repair — 核心問題:「根因是什麼、修好了嗎?」
| 事項 | 訊號 |
|---|---|
| 觸發 | 來源（round 用盡 / 未來:user feedback） |
| 診斷 | root cause + 層級（build_level / plan_level） |
| 修法與結果 | 採取的動作、修後是否通過 |

### 橫切（每 agent 都要）— 成本歸因
tokens / cache 命中 / latency **按 agent 分開記**。三個 agent 拆開了,帳不能再混在一起
—— 這是 Phase 0 之後立刻能兌現的紅利。

### Episode 層（整次 build 的封套）
instruction、最終 plan、self_assessment（ok / verifier / 未來:裁判）、
**user_feedback**（plan 階段 edit;交付後 accept / edit / reject + 原話）、
divergence（自認 OK 但 user 否決 —— 金礦訊號）。

---

## 3. 現況與缺口

現況 `BuildTracer` = 扁平 `llm_calls` 列表（node 名 / prompt / response / tokens）,
存 `/tmp/builder-traces/*.json`。

| 缺口 | 現況 | 本階段改成 |
|---|---|---|
| 無 agent 歸因 | call 只記 node 名 | 每事件標 `agent`（用 Phase 0 預留的 `trace_fields()` 插槽） |
| 只有 LLM call,沒有行為事件 | — | §2 的**結構化事件流**（graph/deterministic 程式碼發出,LLM 不參與記錄決策） |
| 不可查詢 | /tmp 檔案,重開即失,跨 build 不能聚合 | **PostgreSQL 兩表**（§4）,Supervisor 才能下跨 build 查詢 |
| 無 outcome 連結 | trace 止於 build 完成 | Episode 封套 + 交付後 feedback 欄 |

原始 `llm_calls` JSON **保留**當 debug 下鑽層（加 episode_id 交叉參照）,Supervisor 主吃 DB。

---

## 4. 設計

### 4.1 Schema（Flyway V69;prod 手動 psql）

```sql
CREATE TABLE agent_episodes (
  id             BIGSERIAL PRIMARY KEY,
  episode_key    VARCHAR(64) UNIQUE NOT NULL,   -- sidecar session_id
  user_id        BIGINT,
  instruction    TEXT NOT NULL,
  plan_json      TEXT,                          -- 最終 phases（含 user 修改後）
  self_assessment TEXT,                         -- JSON: {ok, verifier_passed, ...}
  user_feedback  TEXT,                          -- JSON list: [{stage, sentiment, text, ts}]
  divergence     BOOLEAN NOT NULL DEFAULT FALSE,-- 自認 OK 但 user reject（派生）
  cost_json      TEXT,                          -- per-agent token/cache/latency 彙總
  status         VARCHAR(24),                   -- finished|failed|handover|partial
  trace_file     TEXT,                          -- /tmp 原始 trace 路徑（debug 下鑽）
  started_at     TIMESTAMPTZ NOT NULL,
  finished_at    TIMESTAMPTZ
);

CREATE TABLE agent_steps (
  id           BIGSERIAL PRIMARY KEY,
  episode_id   BIGINT NOT NULL REFERENCES agent_episodes(id) ON DELETE CASCADE,
  agent        VARCHAR(16) NOT NULL,            -- planner|builder|repair|system
  phase_id     VARCHAR(16),
  event_type   VARCHAR(40) NOT NULL,            -- §4.2 taxonomy
  payload      TEXT,                            -- JSON,依 event_type 定形
  input_tokens INT, output_tokens INT, cache_read INT, latency_ms INT,
  ts           TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_steps_episode ON agent_steps(episode_id);
CREATE INDEX idx_steps_event   ON agent_steps(event_type, ts);
CREATE INDEX idx_steps_agent   ON agent_steps(agent, ts);
```

### 4.2 事件 taxonomy（v1 收斂到 14 種,寧缺勿濫）

| agent | event_type | payload 要點 |
|---|---|---|
| planner | `plan_proposed` | phases 摘要 |
| planner | `plan_user_edited` | **diff**（改了哪個 phase 的什麼） |
| planner | `plan_confirmed` | 最終 phases |
| planner | `replan` | reason |
| builder | `phase_started` / `phase_done` | phase_id, rounds_used |
| builder | `block_picked` | offered[], chosen |
| builder | `param_reject_fix` | block, param, wrong, right |
| builder | `doc_mismatch` | block, field, doc 說 vs 實際 |
| builder | `verifier_reject` | 結構化 reason |
| builder | `stuck_escalated` | 最後 N 動作摘要 |
| repair | `repair_triggered` / `repair_outcome` | source / root_cause, fix_kind, passed |
| system | `llm_usage` | agent 歸因的 per-call tokens/cache/latency |

**發出者一律是 graph / deterministic 程式碼**（在既有事件點掛 hook）;LLM 不決定「要不要記」。
`RoleAgent.trace_fields()`（Phase 0 空插槽）負責补充各 agent 的專屬欄位 —— 填插槽,不改骨架。

### 4.3 寫入路徑（fail-open,絕不拖慢 build）

```
sidecar EpisodeRecorder（in-memory buffer per build）
  → phase 邊界 + finalize 時批次 POST Java /internal/agent-episodes
  → Java 寫 PG
```
- **fire-and-forget + fail-open**:Java 掛了照樣 build,只 log 丟失;絕不在熱路徑同步等待。
- feature flag `ENABLE_AGENT_EPISODES`(default OFF),灰度開。
- 不動 prompt、不動 cache prefix —— 記錄純旁路。

### 4.4 交付後 feedback intake（本階段內含,最小版）

- 結果卡 / pipeline-view 加三鍵:**符合 / 要修改 / 不是我要的**（+選填一句話）。
- POST → Java → `agent_episodes.user_feedback` append;`divergence` 由 DB 派生
  （self ok ∧ user reject）。
- 這同時是未來 Repair post_delivery 觸發與 Planner/Repair fast-path 記憶的**來源事件**
  —— 本階段只記錄,不觸發任何自動行為。

---

## 5. Supervisor v1 怎麼運作（消費端）

**形態:離線週期報告 + 草案,不自動改任何東西**（分層自治,先最保守檔）。

| 查詢（跨 build SQL） | 判斷 | 產出（草案,人工 review） |
|---|---|---|
| `param_reject_fix` 按 (block,param) 聚合 Top-N | **doc 不齊** | block doc 修正建議清單 |
| `doc_mismatch` 按 block 聚合 | doc 失真 | 同上（fix 級） |
| `plan_user_edited` diff 的重複 pattern | 規劃知識缺 | preference / domain 記憶草案 |
| 各 phase 型態平均 rounds 趨勢 | 執行效率退化 | 指出退化起點（哪次部署後） |
| per-agent cost 趨勢（cache%、tokens/build） | 成本回歸 | 報告 + 定位 |
| `divergence=true` 的 episode 清單 | 意圖沒抓對 | 逐案摘要供人工檢討 |
| `repair_outcome` root_cause 分佈 | 系統性上游問題 | correction 草案（tag planner/builder） |

實作:sidecar 週期 job（或手動觸發）跑查詢 → 產 markdown 報告（存 DB + 可下載）。
自動寫回記憶 / doc = 下一階段,依 harness 設計走「草案 → review → 版本化」。

---

## 6. Step-by-Step Execution Plan

| Step | 內容 | 驗證 |
|---|---|---|
| 1 | V69 兩表 + Java internal API（flag OFF） | 單測;flag OFF 全行為不變 |
| 2 | sidecar `EpisodeRecorder`（buffer / 批次 / fail-open）+ episode 生命週期接線 | 單測(fail-open 三情境);SLASH smoke |
| 3 | Planner 事件（含 confirm gate 的 user-edit diff） | 造一次人工編輯,DB 見 diff |
| 4 | Builder 事件（param_reject_fix / doc_mismatch / verifier_reject / rounds） | 強迫一次 param 錯,DB 見事件 |
| 5 | Repair 事件 + `llm_usage` per-agent 歸因（trace_fields 插槽） | cost SQL 能按 agent 分組 |
| 6 | 交付後 feedback 三鍵（前端最小版）+ divergence 派生 | 點「不是我要的」→ DB 見 feedback + divergence |
| 7 | Supervisor v1 報告 job + 用真實資料出第一份報告 | 報告含 §5 各節,數字可對回 SQL |
| 8 | 閘門:SLASH-17 全套 + overhead 量測 | 零回歸;overhead < 3% wall |

---

## 7. Edge Cases & Risks

- **熱路徑性能**:記錄一律旁路 buffer + 批次;驗收含 overhead 上限（< 3% wall-clock）。
- **量**:17-case 全套 ≈ 數百 steps/日常量級,PG 無壓力;保留策略 90 天（episodes 彙總永久留,steps 過期清）。
- **fail-open**:Java/PG 不可用 → build 照常,事件丟棄 + log 一行。絕不因觀測弄壞生產。
- **cache**:不碰 prompt 組裝,cache prefix 不變 —— 但驗收仍驗 cache% 不退。
- **不做（本階段明確排除）**:Supervisor 自動寫回（下一階段）、memory class 欄位
  （Phase 3）、業務監控平面（往後排）、v27 legacy path 事件化。

---

## 8. 待拍板（簽核前定,含建議預設）

| # | 問題 | 建議預設 |
|---|---|---|
| G1 | 儲存進 PG（Java 管）vs sidecar 本地輕量 | **PG**（跨 build 查詢是硬需求） |
| G2 | 交付後 feedback 三鍵本階段做不做 | **做**（最小版;它是 divergence 與未來所有學習的源頭） |
| G3 | Supervisor v1 觸發 | **手動 + 週期(cron 週報)** 皆可跑 |
| G4 | steps 保留天數 | 90 天(episodes 永久) |

---

## 9. 驗收條款（Acceptance Checklist — 與 spec 一起簽核）

| # | 條款 | user 驗證方式 |
|---|---|---|
| C1 | flag OFF 全行為不變（default） | 部署後跑 build,無任何差異;DB 無新列 |
| C2 | flag ON 後每次 build 產 1 episode + steps 進 PG | 跑 1 個 build → `SELECT` 兩表可見 |
| C3 | 100% steps 有 agent 歸因 | `SELECT count(*) FROM agent_steps WHERE agent IS NULL` = 0 |
| C4 | param 猜錯→改對 有事件 | 看任一含 verifier reject 的 build → `param_reject_fix` 列存在 |
| C5 | confirm gate 編輯 plan → diff 入庫 | 手動改一個 phase → `plan_user_edited` payload 含 diff |
| C6 | 成本可按 agent 聚合 | 跑指定 SQL → 三個 agent 各自 tokens/cache% 出數字 |
| C7 | 交付後三鍵可用且入庫 | 點「不是我要的」→ episode.user_feedback + divergence=true |
| C8 | fail-open | build 中途停 Java → build 照常完成 |
| C9 | Supervisor v1 報告可出 | 觸發後拿到含 doc-gap Top-N / plan-edit pattern / cost 趨勢的報告 |
| C10 | overhead < 3% wall | flag ON/OFF 各跑 3 案對比 |
| C11 | SLASH-17 零回歸 + cache 40–58% 維持 | 全套閘門 |

---

**簽核**:請確認 §8 G1–G4（照建議就說「照建議」）與 §9 驗收條款增刪。
定案後回覆「開始開發」,我依 §6 Step 1 起手。
