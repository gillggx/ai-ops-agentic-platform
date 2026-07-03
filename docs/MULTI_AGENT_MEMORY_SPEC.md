# Multi-Agent 記憶層 — Schema + 三 Agent 寫入 Tech Spec

> Draft v1 · 2026-07-03。= Q4 順序的 ②+③+④。承接 `AGENT_HARNESS_DESIGN.html`
> §3(6 class × 3 軸)/ §9(matrix)/ §10(Builder 文件備忘)/ §12(B 記錄行為),
> 與已交付的觀測層(C1–C11)。
> 驗收條款(§7)與 spec 一起簽核;待拍板(§6)先答。

---

## 1. Context & Objective

觀測層已通:episodic 原料在流(23 episodes / 750 steps)、divergence 訊號有了。
**本階段讓 agent 開始「寫筆記」**:被 user 糾正、被 verifier 教訓過的事,變成
下次 build 讀得到的 durable memory —— 對齊 §9 矩陣中 episodic 以外的 5 個 class
的**寫入側**(讀取側 v1 走既有 RAG 管線,零新 code,見 §3.3)。

**非目標**:Supervisor 蒸餾/curation(⑤)、L2 語意裁判、監控平面。

---

## 2. 設計原則(沿用已定案)

- **寫入時機 = graph deterministic 事件**(B 表),LLM 不決定「要不要記」。
- **v1 memo 內容 = deterministic 模板填 diff/事實**,不加 LLM 呼叫(cost-first;
  LLM 蒸餾留給 Supervisor)。→ 待拍板 E1。
- **Builder 的積木 know-how 進 `block_doc_memos`**(文件旁的便利貼,審核佇列),
  不污染 agent_knowledge(單一來源原則)。
- **per-user**:preference/presentation 寫入帶 build 的 user_id
  (檢索本來就按 user_id 過濾,Q3 決策自然落地)。
- flag `ENABLE_MEMORY_WRITES`(default OFF),fail-open,絕不影響 build。

---

## 3. Architecture & Design

### 3.1 Schema(V70,prod 手動 psql)

```sql
-- (a) agent_knowledge 加 class 維度(§3 的第 4 軸)
ALTER TABLE agent_knowledge ADD COLUMN memo_class VARCHAR(16)
  CHECK (memo_class IN ('domain','preference','presentation',
                        'correction','episodic','procedure'));
-- 既有列維持 NULL = legacy 未分類 → 檢索行為完全不變(零回歸)
-- 新增列一律必填 memo_class

-- (b) Builder 文件備忘(AGENT_HARNESS_DESIGN §10)
CREATE TABLE block_doc_memos (
  id           BIGSERIAL PRIMARY KEY,
  block_id     VARCHAR(100) NOT NULL,
  param        VARCHAR(100),
  memo         TEXT NOT NULL,             -- deterministic 摘要
  verdict_context TEXT,                   -- reject payload(s) JSON
  from_episode VARCHAR(64),               -- episode_key 溯源
  status       VARCHAR(16) NOT NULL DEFAULT 'pending',  -- pending|promoted|discarded
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  reviewed_by  BIGINT, reviewed_at TIMESTAMPTZ
);
CREATE INDEX idx_bdm_block_status ON block_doc_memos(block_id, status);
```

### 3.2 寫入路徑(填 Phase 0 預留的 record-hook 插槽)

| # | Agent | 觸發(graph 事件,觀測層已在偵測) | 寫什麼 | 去哪 |
|---|---|---|---|---|
| W1 | Planner | confirm gate 有 user edit(現有 plan_user_edited 的來源) | 決策樹分類 → preference / presentation / correction(帶 from/to + why=user 明改) | agent_knowledge(user 域) |
| W2 | Builder | phase_done 且該 phase 有 verifier rejects(現有 param_reject_fix 的來源) | block/param + 錯法 + 過法摘要 | **block_doc_memos**(pending) |
| W3 | Repair | repair_outcome | 根因摘要 correction,`applies_to` 標 plan/execute | agent_knowledge |

- **分類決策樹(deterministic,不讓 LLM 挑)**:edit 動到 expected/圖種字樣 →
  presentation;動到時間窗/機台/範圍等慣性參數 → preference;否則 → correction。
- **防洪**:每 build 上限 agent_knowledge ≤3 筆、doc_memos ≤5 筆;同 (user,
  memo_class, title) 已存在 → 跳過(dedup);全部 fail-open。
- 寫入走既有 Java internal knowledge API(擴充支援 memo_class)+ 新 doc-memos
  internal endpoint;sidecar 不碰 PG。

### 3.2b 總表:6 Memory × 3 Agent — 何時讀 / 何時寫

> 完整版(含 durable 寫入者與 timing 細節)見 `AGENT_HARNESS_DESIGN.html` §9.0;
> 此處為實作對照。粗體 = 本階段落地的 fast-path 寫入(W1–W3)。

| class | PLANNER | BUILDER | REPAIR |
|---|---|---|---|
| domain | 讀:每次規劃 / 寫:— | 讀:選 block(多在 block_docs)/ 寫:— | 讀:修正時 / 寫:—(S 蒸餾) |
| preference | 讀:每次規劃 / **寫:plan edit 屬偏好(W1)** | — | 讀:修正時 / **寫:feedback 屬偏好** |
| presentation | 讀:定輸出型態 / **寫:改呈現形式(W1)** | 讀:建 chart phase / 寫:— | 讀寫:feedback 屬形式時 |
| correction | 讀:規劃(tag=plan)/ **寫:糾正 plan 邏輯(W1)** | 讀:選 block(tag=execute)/ 寫:—(走 doc 備忘 W2) | 讀:修正起始 / **寫:定位根因(W3,主)** |
| episodic | 只寫(已上線,觀測層) | 只寫 + **doc 備忘(W2)** | 只寫 |
| procedure | 讀:重用 plan 形狀 / 寫:—(S 蒸餾) | 讀:重用配方 / 寫:—(S 蒸餾) | 讀:重用修 pattern / 寫:— |

### 3.2c Supervisor 修正迴路(下一階段⑤;log 訊號本階段已備妥)

Supervisor **不改 agent 的 code/prompt,只改 agent「讀的東西」**(knowledge/doc)+
預算建議,草案經人審。完整表見 `AGENT_HARNESS_DESIGN.html` §11.1;摘要:

| 對象 | log 訊號 | 修正(草案) | 可量測閉環 |
|---|---|---|---|
| Planner | plan_user_edited 重複 pattern / divergence 清單 / replan 趨勢 | preference·presentation·correction(tag=plan)草案 | edit 率、divergence 率下降 |
| Builder | verifier_reject/param_reject_fix 聚合 + pending doc 備忘 / 錯選 pattern / rounds·成本趨勢 | block_docs 修正草案(DOC_GAP)/ execute-tag correction / tier·budget 建議 | 同 block reject 數下降(doc 自癒) |
| Repair | 同 root-cause 重犯 / 成功率趨勢 | correction 召回檢查→PROMOTE 或改寫 / 蒸餾 procedure | 重犯率、handover 率下降 |

### 3.3 讀取側(v1 = 零新 code,這是本設計的關鍵槓桿)

新寫入的 agent_knowledge 列 = 普通知識列:30s 背景 job 自動補 embedding →
**既有 plan/execute 檢索管線自動撿到**(user_id 過濾已存在)。`memo_class` 在
v1 是 Supervisor/curation 用的中繼資料,不改變檢索。
`block_doc_memos` v1 只進 Supervisor 報告(新 section「待審 doc 備忘 Top-N」);
BlockDocsDrawer 徽章列後續(→ E3)。

### 3.4 學習閉環的最小驗證(D3 的本質)

user 在 build A 改了 plan(如「24 小時 → 12 小時」)→ W1 寫 preference →
build B(同 user、同類需求)的 goal_plan knowledge hint **出現這條** →
證明「寫的筆記下次讀得到」。

---

## 4. Step-by-Step Execution Plan

| Step | 內容 | 驗證 |
|---|---|---|
| 1 | V70 schema + Java:knowledge API 支援 memo_class + doc-memos endpoint(Mockito) | 單測;既有列 NULL 不變 |
| 2 | sidecar MemoryWriter(dedup + caps + fail-open;掛 record-hook 插槽) | 單測(cap/dedup/fail-open) |
| 3 | W1 Planner(confirm gate diff → 分類樹 → 寫入) | e2e:編輯 plan → DB 見分類正確的列 |
| 4 | W2 Builder(rejects → doc memo)+ W3 Repair(correction) | e2e:reject build → pending memo;repair → correction |
| 5 | 讀取閉環驗證(§3.4)+ Supervisor 報告加 doc-memo section | build B hint 含 build A 寫的筆記 |
| 6 | 閘門:SLASH-17 + cache + flag OFF 零寫入 | 零回歸 |

---

## 5. Edge Cases & Risks

- **記憶污染**:錯的筆記會誤導後續 build → 防護 = 上限 + dedup + Supervisor 可
  prune(⑤);preference 只從「user 明改」產生(最高可信訊號,Q1 判準)。
- **檢索噪音**:新列進 RAG 可能擠掉舊知識(top-k 固定)→ v1 量小(≤3/build)+
  D10 驗證舊行為;若觀察到噪音,Phase 5 用 PROMOTE/DEMOTE 調。
- **cache**:寫入在 confirm/收尾時發生,不動 prompt prefix。
- **不做**:LLM 填 memo(E1)、自動改 block_docs 正文(備忘永遠只是候選)。

---

## 6. 待拍板(含建議)

| # | 問題 | 建議 |
|---|---|---|
| E1 | memo 內容:deterministic 模板 vs LLM 填空 | **模板**(零成本、可測;蒸餾留 Supervisor) |
| E2 | fast-path 寫入即 active=true?或 draft 待審 | **active=true**(立即生效;Supervisor 事後 prune — Q2 你已選「兩路都要+Supervisor 整理」) |
| E3 | BlockDocsDrawer 顯示待審備忘徽章 | **後續**(v1 只進 Supervisor 報告) |
| E4 | 防洪上限 | knowledge ≤3、doc_memos ≤5 / build(env 可調) |

---

## 7. 驗收條款(與 spec 一起簽核)

| # | 條款 | user 驗證方式 |
|---|---|---|
| D1 | flag OFF(default)零寫入 | OFF 跑 build → 兩表零新列 |
| D2 | V70 後既有知識列不變(NULL=legacy) | 檢索行為 diff = 0;既有 39+ 列 memo_class IS NULL |
| D3 | **學習閉環**:build A 改 plan → build B 的 hint 出現該筆記 | §3.4 兩段 e2e,trace 可見 hint 內容 |
| D4 | 編輯分類正確 | 改圖種→presentation;改時間窗→preference(各驗一次) |
| D5 | reject phase → pending doc memo(帶 block/param/溯源) | SELECT block_doc_memos |
| D6 | repair → correction(applies_to 有標) | SELECT agent_knowledge WHERE memo_class='correction' |
| D7 | dedup:同編輯重複兩次 → 只一列 | 重跑同編輯 |
| D8 | caps 生效 | 構造 >3 edits → 只寫 3 |
| D9 | Supervisor 報告有「待審 doc 備忘」section | 重跑 report |
| D10 | SLASH-17 零回歸 + cache 帶內 + 舊 RAG 不變 | 閘門 |

---

**簽核**:請回 E1–E4(照建議就說「照建議」)+ D1–D10 增刪。定案後回覆
「開始開發」,我依 §4 Step 1 起手。
