# Agent Activity 頁 — Tech Spec

> Draft v1 · 2026-07-03。把已上線的 agent_episodes / agent_steps 變成產品內
> 的可視化頁面。設計基準:`docs/AGENT_TRACE_UI_PROPOSAL.html`。
> 決策:兩視圖都做 · 新頁 `/agent-activity` · 記憶讀取列出召回哪幾條。
> 驗收條款(§6)與 spec 一起簽核。

---

## 1. Context & Objective

觀測層在收 episodic(WRITE 事件),但**沒記「讀了哪些記憶」**,也沒有讀 API /
頁面。本階段:(a) 補 read-log,(b) 開 read API,(c) 做 `/agent-activity` 頁的
兩個視圖 —— 讓 3 個 agent 的行為(尤其記憶讀/寫)看得見。

**非目標**:改任何 build 行為;Supervisor 寫回(Phase 5)。

---

## 2. 新增:記憶讀取 log（read-log）

現在只有 WRITE(W1/W2/W3)進 agent_steps;READ 沒記。補一個事件:

- **event_type `memory_recall`** — 在既有知識注入點發出(不新增 LLM 呼叫、不動 prompt):
  - plan 層:`goal_plan` 的 `build_knowledge_hint` 回傳 rows 時
  - execute 層:phase_loop 注入 execute-knowledge 時
  - payload:`{layer, recalled: [{id, memo_class, title[:60], score}]}`
- 由 `EpisodeRecorder.record("memory_recall", agent=…, phase_id=…)` 寫,
  **fail-open**、gated under 既有 `ENABLE_AGENT_EPISODES`。
- 這樣時間軸的「記憶軌」能同時畫 **讀(memory_recall)** 與 **寫(W1/W2/W3)**。

---

## 3. Java 讀 API（user-facing，ADMIN_OR_PE）

新 `AgentActivityController` `@RequestMapping("/api/v1/agent-activity")`
`@PreAuthorize(ADMIN_OR_PE)`(比照 AgentEpisodeController):

| 端點 | 回傳 |
|---|---|
| `GET /episodes?limit=30` | 近期 build 列表:{episode_key, instruction, status, divergence, step_count, cost 摘要, started_at}(build picker 用) |
| `GET /episodes/{key}` | 單 build:episode 封套 + **依 ts 排序的 steps**(swim-lane 用) |
| `GET /report?days=30` | 轉呼叫既有 SupervisorReportService(記分板用) |

讀取 service 方法走既有 repository(`findByEpisodeIdOrderByTsAsc` 已有)。

---

## 4. 前端 `/agent-activity`（兩視圖分頁）

- 導覽加一項(ADMIN_OR_PE 可見)。頁內兩分頁:
  - **分頁 A「Build 時間軸」**(視圖①):左 = 近期 build 列表(picker),右 =
    選中 build 的 swim-lane —— Planner / Builder / Repair + 記憶軌,依
    `AGENT_TRACE_UI_PROPOSAL.html` 版型。橫軸 = **phase 進程**(非真實時間)。
    事件 chip 上色:action / pass(綠)/ verifier_reject(紅)/ 記憶 讀(灰)寫(綠)。
    右欄:self_assessment vs user_feedback → divergence 徽章 + per-agent 成本。
  - **分頁 B「記分板」**(視圖②):3 agent 成績卡 + doc-gap 長條 + divergence 清單
    + 待審 doc 備忘,資料來自 `/report`。
- 所有後端互動走 Next `/api/agent-activity/*` proxy(authHeaders → Java)。

---

## 5. Step-by-Step

| Step | 內容 | 驗證 |
|---|---|---|
| 1 | `memory_recall` 事件:knowledge 注入點發出 + 單測 | recall 進 agent_steps |
| 2 | Java read API(list / detail / report proxy)+ Mockito | 端點回正確形狀 |
| 3 | Next proxy routes `/api/agent-activity/*` | 200 透傳 |
| 4 | 分頁 A swim-lane(真實資料渲染) | 選一個 build → 三軌 + 記憶讀寫都出來 |
| 5 | 分頁 B 記分板 | 數字對得回 report |
| 6 | 閘門:SLASH-17 零回歸(recall 寫入是旁路) | strict/cache 不退 |

---

## 6. 驗收條款（與 spec 一起簽核）

| # | 條款 | user 驗證方式 |
|---|---|---|
| U1 | `/agent-activity` 頁存在、ADMIN_OR_PE 可進 | 登入開頁 |
| U2 | 分頁 A:選一個 build → swim-lane 出 Planner/Builder/Repair 三軌 | 點列表任一 build |
| U3 | **記憶軌同時顯示 讀 與 寫** | 有編輯/有 reject 的 build → 讀(memory_recall 列出召回哪幾條)+ 寫都在 |
| U4 | verifier_reject 紅 / pass 綠 / repair 未觸發標示 | 看有 reject 的 build |
| U5 | 右欄 self vs user + divergence 徽章 | 開那筆 divergence=true 的 build |
| U6 | 分頁 B 三 agent 成績卡 + doc-gap 長條 + divergence 清單 | 切記分板 |
| U7 | memory_recall 有列出具體召回(id/class/title) | 開一個規劃有讀知識的 build |
| U8 | flag OFF(ENABLE_AGENT_EPISODES=0)頁面優雅空狀態、build 不受影響 | 關 flag 跑 build |
| U9 | SLASH-17 零回歸 + cache 帶內 | 閘門 |

---

**簽核**:符合請回「開始開發」,我依 §5 Step 1 起手。
