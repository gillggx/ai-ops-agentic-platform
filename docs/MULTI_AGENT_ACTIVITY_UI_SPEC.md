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

## 2. 新增:記憶引用 log（read-log,逐 call/round）

主視圖要像原本的 build trace(多 phase、每 round 的 prompt + output);**唯一
要加的能力 = 讓那段 prompt 認得出引用了哪條 memory**。BuildTracer 已逐 call 記
`user_msg`/`raw_response`/phase/round,缺的是「這個 call 的 prompt 注入了哪幾條
知識」。補:

- **event_type `memory_recall`** — 在既有知識注入點發出(不新增 LLM 呼叫、不動 prompt):
  - plan 層:`goal_plan` 的 `build_knowledge_hint` 回傳 rows 時
  - execute 層:phase_loop 注入 execute-knowledge 時
  - payload:`{layer, round, recalled: [{id, memo_class, title[:60], score}]}`
  - **必含 `round`(對齊 BuildTracer 的 round)**,好讓 UI 把「引用記憶」貼到
    對應那一次 LLM call 的 prompt 旁。
- 由 `EpisodeRecorder.record("memory_recall", agent=…, phase_id=…)` 寫,
  **fail-open**、gated under 既有 `ENABLE_AGENT_EPISODES`。
- （進階,可 v1.1)在 user_msg 裡把知識區段用 sentinel 包起來,UI 直接高亮
  該 span;v1 先用「round → recalled 清單」做旁標,不動 prompt。

---

## 3. Java 讀 API（user-facing，ADMIN_OR_PE）

新 `AgentActivityController` `@RequestMapping("/api/v1/agent-activity")`
`@PreAuthorize(ADMIN_OR_PE)`(比照 AgentEpisodeController):

| 端點 | 回傳 |
|---|---|
| `GET /episodes?limit=30` | 近期 build 列表:{episode_key, instruction, status, divergence, step_count, cost 摘要, started_at}(build picker 用) |
| `GET /episodes/{key}` | 單 build:episode 封套 + **依 ts 排序的 steps**(含 memory_recall) |
| `GET /episodes/{key}/rounds` | **對齊 build trace 的逐 round 明細**:讀 BuildTracer JSON(sidecar 透傳),回 `[{phase_id, round, node, user_msg(prompt), raw_response(output), tokens, cache}]`,並把同 (phase,round) 的 `memory_recall.recalled` merge 進去 |
| `GET /report?days=30` | 轉呼叫既有 SupervisorReportService(記分板用) |

steps 走既有 repository(`findByEpisodeIdOrderByTsAsc`);rounds 端點讀
`agent_episodes.trace_file`(BuildTracer 已存路徑)+ merge memory_recall。

---

## 4. 前端 `/agent-activity`（兩視圖分頁）

- 導覽加一項(ADMIN_OR_PE 可見)。頁內:左 = 近期 build 列表(picker),右 =
  選中 build 的三分頁:
  - **分頁 A「Trace 明細」(主,像原本的 build trace)**:逐 phase → 逐 round,
    每 round 展開顯示 **run 的 prompt(user_msg)+ output(raw_response)**,
    以及 **本 round 引用的記憶**(memory_recall 的 recalled 清單:id/class/title,
    可點跳記憶帳本;prompt 內知識區段旁標「引用記憶」)。verifier_reject 標紅。
    這是使用者最熟悉、你指定的核心視圖。
  - **分頁 B「時間軸概覽」**(視圖①,降為概覽):swim-lane —— Planner/Builder/
    Repair + 記憶讀寫軌,快速看整體節奏;細節回分頁 A 看。
  - **分頁 C「記分板」**(視圖②):3 agent 成績卡 + doc-gap 長條 + divergence
    清單 + 待審 doc 備忘,資料來自 `/report`(跨 build)。
- 右欄(所有分頁共用):self_assessment vs user_feedback → divergence 徽章 +
  per-agent 成本。
- 所有後端互動走 Next `/api/agent-activity/*` proxy(authHeaders → Java)。

---

## 5. Step-by-Step

| Step | 內容 | 驗證 |
|---|---|---|
| 1 | `memory_recall` 事件(含 round):knowledge 注入點發出 + 單測 | recall 進 agent_steps,payload 有 round + recalled |
| 2 | Java read API(list / detail / **rounds** / report proxy)+ Mockito | rounds 端點回 prompt+output+引用記憶 |
| 3 | Next proxy routes `/api/agent-activity/*` | 200 透傳 |
| 4 | **分頁 A Trace 明細**(逐 round prompt/output + 引用記憶標註) | 選 build → 看到 prompt、output、引用的記憶 id/class |
| 5 | 分頁 B swim-lane 概覽 + 分頁 C 記分板 | 三軌出來;數字對得回 report |
| 6 | 閘門:SLASH-17 零回歸(recall 寫入是旁路) | strict/cache 不退 |

---

## 6. 驗收條款（與 spec 一起簽核）

| # | 條款 | user 驗證方式 |
|---|---|---|
| U1 | `/agent-activity` 頁存在、ADMIN_OR_PE 可進 | 登入開頁 |
| U2 | **分頁 A 像原本 build trace**:多 phase → 逐 round 看得到 run 的 prompt + output | 點列表任一 build,展開 round |
| U3 | **每 round 的 prompt 旁顯示「引用了哪條 memory」(id/class/title)** | 開一個規劃有讀知識的 build → round 旁有引用記憶清單 |
| U4 | 記憶「寫入」(W1/W2/W3)也標得出來(哪個 round 寫了什麼) | 有編輯/有 reject 的 build |
| U5 | verifier_reject 紅標 / repair 觸發與否可辨 | 看有 reject 的 build |
| U6 | 右欄 self vs user + divergence 徽章 | 開 divergence=true 的 build |
| U7 | 分頁 B swim-lane 概覽 + 分頁 C 記分板(成績卡/doc-gap/divergence) | 切分頁 |
| U8 | flag OFF(ENABLE_AGENT_EPISODES=0)頁面優雅空狀態、build 不受影響 | 關 flag 跑 build |
| U9 | SLASH-17 零回歸 + cache 帶內 | 閘門 |

---

**簽核**:符合請回「開始開發」,我依 §5 Step 1 起手。
