# Multi-Agent Build 平面 — 設計 + Phase 0 Tech Spec

> Draft v2 · 2026-07-02。承接 `AGENT_HARNESS_DESIGN.html` / `MULTI_AGENT_ARCHITECTURE.html`。
> 決策前提:D1 = 結構重構先;D2 = 監控平面納入本 effort（Phase 1）。
>
> **界線**:本文把 Planner/Builder/Repair 的**目標互動契約**先定義好（讓架構撐得住），
> 但 Phase 0 實際只做「把現有 flow 包成 agent + registry、零行為改變」。哪些是「重新框」、
> 哪些是「後面 phase 才長出的新行為」，每段都標清楚。

---

## 1. Context & Objective

**現況**:builder 是單一 LangGraph、單一 LLM、單一 prompt 語境。`goal_plan` /
`agentic_phase_loop` / `phase_verifier` / `phase_revise` 是 node，但共用一切。

**目標**:拆成 **Planner / Builder / Repair** 三個 role agent，各有獨立
prompt / model / tools / context view，並把三者的**協作契約**講清楚，達到關注點分離、
可獨立單測、改一處只動一個 agent。

---

## 2. Agent 的組成元素（先設計 agent，再談協作）

每個 agent 由 **11 個元素**組成。關鍵洞察:**現有 LangGraph 的東西幾乎都能直接餵進來** ——
重構大半是「把散落在 node 裡的這些，收攏成 agent 的顯性欄位」。

| # | 元素 | 說明 | 現 LangGraph 來源（餵給它） |
|---|---|---|---|
| 1 | **Charter / 憲章** | 角色定位 + 不可違反的硬規則 | 各 node system prompt 的開頭段 |
| 2 | **System prompt** | 單一職責提示 | 各 node 的 prompt 組裝函式 |
| 3 | **Model cfg** | 模型 / reasoning effort / cache | `get_llm_client` + settings |
| 4 | **Tools（allowed）** | scoped 工具白名單 | node 內宣告的 tools 列表 |
| 5 | **State view（in）** | 讀 shared state 的哪一塊（compact） | `_build_observation_md` / `_build_canvas_diff_md` |
| 6 | **Output patch（out）** | 回寫 shared state 的哪一塊 | `GraphState` reducers（`_replace` / `_extend_list`） |
| 7 | **Budgets** | round / retry / recursion 上限 | `MAX_REACT_ROUNDS=32` / `MAX_REVISE=1` / `recursion_limit=60` |
| 8 | **協作協定** | 何時交手 / 請 review / 升級 | graph 的 conditional edges（verifier→advance/reject；revise→retry/handover） |
| 9 | **Memory hooks（read）** | inference 時讀哪些 class | *（Phase 3 slot；Phase 0 先留介面）* |
| 10 | **Record hooks（write）** | 何事件觸發記錄 | *（Phase 4 slot；對應 B 表的觸發事件）* |
| 11 | **Trace emit** | 記進 Episode 的欄位 | `BuildTracer`（Phase 2 擴充成 Episode） |

> 元素 1-8 = Phase 0 就從 LangGraph 收攏（行為不變）;9-11 = 先留**空介面**，後面 phase 填內容，
> 骨架不再動。這就是「先設計好 agent 元素，讓後續 phase 只填不改骨」。

---

## 3. Planner ↔ Builder：怎麼 cowork

### 3.1 交付物契約（Planner 給 Builder 什麼）
Planner 規劃完，產出**一組 phase**，每個 phase 是一份**單 phase plan**:
```
Phase = {
  id,                # p1, p2...
  goal,              # 這個 phase 的意圖（一句話，不含 block 名）
  expected,          # 產出「種類」:raw_data|transform|verdict|chart|table|scalar|alarm
  expected_output,   # 產出的「語意」描述（Planner 判對錯的依據）
  constraints,       # 硬限制（時間窗、機台、不可用的做法…）
  why                # 為何需要這 phase
}
```
Builder **一次吃一個 phase**，跑 ReAct（inspect / add_node / connect / set_param），
產出覆蓋該 phase 的 canvas 節點。

### 3.2 兩層 review（Builder 何時找 Planner）
| 層 | 誰做 | 檢什麼 | 成本 | Phase |
|---|---|---|---|---|
| **結構驗證** | Verifier（deterministic node，不 agent 化） | covers / orphan / leaf | 便宜、每 phase | **Phase 0 已有** |
| **語意裁判** | **Planner（判對錯）** | 產出是否真的符合 phase 意圖（expected_output） | 一次 LLM | **新，Phase 2+** |

### 3.3 Builder → Planner 的觸發（全是 deterministic graph 事件，不靠 LLM 自由意志）
| 觸發 | 意思 | Planner 動作 |
|---|---|---|
| **PHASE_DONE** | 結構驗證過了 | 語意裁判:符合 expected_output? |
| **STUCK** | round 用盡仍過不了 | 判斷是 Builder 執行問題還是 plan 問題 |
| **INFEASIBLE** | 沒有 block 能覆蓋此 phase（能力缺口） | **REPLAN** 或標記能力缺口 |
| **AMBIGUOUS** | plan 對某決策沒交代清楚 | 補充 constraints |

### 3.4 Planner 的裁決（verdict）
- **APPROVE** → 前進下一 phase
- **REVISE** → 給 Builder 一句 feedback，Builder 留在原 phase 再試
- **REPLAN** → Planner 改這個（或下游）phase 的 plan，Builder 重跑受影響 phase

### 3.5 一次典型協作（happy + unhappy）
```
Planner  ── phases[] ──▶  Builder
                          Builder 執行 p1 → Verifier(結構) ✓ → PHASE_DONE
Builder  ── 結果 ──────▶  Planner 語意裁判
   ├ APPROVE ─▶ Builder 執行 p2 ...
   ├ REVISE  ─▶ Builder 同 p1 再修（帶 feedback）
   └ REPLAN  ─▶ Planner 改 p1 plan ─▶ Builder 重跑 p1
（STUCK / INFEASIBLE 亦走 Builder→Planner，Planner 決定 REVISE / REPLAN / 升級 Repair）
```
> **Phase 0 現況**:只有「結構驗證 + Builder 內建自省（phase_revise）」在跑（=現有行為）。
> **語意裁判 + REPLAN 迴路**是 Phase 2 之後長出來的（需要 Planner 有裁判 prompt + Episode 記裁決）。
> Phase 0 先把 3.1 的 phase 契約、3.3 的觸發介面定義好，行為不變。

---

## 4. Repair：何時接手、修什麼、怎麼執行

直接回答你的四個問題:

### 4.1 是「前者完成他再接手」嗎？→ **不是,不 auto-chain**
build 完成即**交付給 user**。Repair 不會在 Planner/Builder 一做完就自動接手。

### 4.2 那何時接手？→ **feedback 驅動**,兩個觸發源
| 觸發 | 情境 | 來源 |
|---|---|---|
| **in-build escalation** | Planner 語意裁判 REJECT，且 Builder 自省（phase_revise）用盡 | 系統內部 |
| **post-delivery** | **user 在對話視窗說「不是我要的」** | user |

> 澄清一個容易混的點:**Builder 內建的 `phase_revise`（卡住自省重試）不是 Repair** ——
> 那是 Builder 自己的自癒,不需要人。**RepairAgent 是「跨 Planner/Builder、根因級」的修正者**,
> 由 feedback 觸發（尤其你講的 post-delivery user 反應）。

### 4.3 是「修正」還是「給修正的 plan」？→ **先診斷層級,兩者都做**
Repair 的核心推理 = **診斷這個問題該在哪一層修**:
| 診斷 | 例子 | Repair 動作 |
|---|---|---|
| **build-level（局部）** | 參數錯、選錯 block、呈現形式錯 | **直接 patch canvas**（surgical） |
| **plan-level（結構）** | 意圖抓錯、phase 拆錯、少一個 phase | **產修正 plan → 交回 Planner** |

### 4.4 怎麼執行？
Repair 操作**同一份 shared state（canvas + phases）**:
- **direct-patch**:用 canvas ops（add/connect/set_param/remove）動最小範圍 → 重跑 Verifier → 交付。
- **re-plan**:產出修正後的 phases → Planner confirm →**只重跑受影響的 phase**（非全重建）→ 交付。

Repair 吃的三路輸入(原 prompt + 現 pipeline + feedback)先做 4.3 的診斷,再走對應執行路徑;
它學到的「原本哪裡錯」寫成 **correction**（tag 給 Planner 或 Builder），下次避免重犯。

> **Phase 0 現況**:post-delivery feedback channel 還沒有（那是 Phase 2 C#1）,所以 Repair 的
> 「feedback 驅動接手」要 Phase 2 才真的通。Phase 0 先把 RepairAgent 包好（承接現有 phase_revise
> 的自省邏輯），介面（三路輸入 + 診斷 + patch/re-plan 出口）先定義。

---

## 5. Phase 0 到底改什麼（誠實界線）

| 項目 | Phase 0 做 | 之後 phase |
|---|---|---|
| Agent 契約 + 11 元素（1-8） | ✅ 從 LangGraph 收攏 | — |
| Registry（集中 prompt/model/tools） | ✅ | — |
| Planner→phases、Builder 執行、結構 Verifier、Builder 自省 | ✅ 重新框，行為不變 | — |
| Planner 語意裁判 + REPLAN 迴路 | 介面定義 | Phase 2+ 長行為 |
| Repair feedback 驅動 + 診斷 + patch/re-plan | 介面定義（承接自省） | Phase 2+ 長行為 |
| Memory / 記錄 / Episode（元素 9-11） | 留空介面 | Phase 2-5 |

**一句話**:Phase 0 是「把現有 flow 換上 agent 的骨架與契約，零行為改變」;3、4 節描述的
完整 cowork（語意裁判、REPLAN、Repair 診斷）是**這副骨架讓它們 Phase 2+ 能長出來**。

---

## 6. Step-by-Step Execution Plan（Phase 0）

每步一個小 PR，**SLASH-17 當回歸閘**，可獨立 review / rollback。

1. `Agent` base（元素 1-8）+ registry skeleton + 空的 memory/record/trace 介面（9-11）。
2. `goal_plan` → `PlannerAgent`（含 3.1 phase 契約 + 3.3 觸發介面）;SLASH-17 = baseline。
3. `agentic_phase_loop` → `BuilderAgent`;SLASH-17。
4. `phase_revise` → `RepairAgent`（含 4.3/4.4 的診斷 + 出口介面，但暫只承接原自省行為）;SLASH-17。
5. 集中 config 到 registry;移除散落常數。
6. 全套 SLASH-17 回歸:strict 品質 / 成本 / **cache 命中 40-58%** 三項齊看。

---

## 7. Edge Cases & Risks

- **Prompt-cache prefix 變動**:拆 prompt 改變 cache 斷點 → 每步驗 `cache_read` 仍 40-58%。
- **Token 爆量**:agent 交接必須重用 compact state view（3.1/元素 5），不可重展 context。
- **不可退回 supervisor-LLM**、**Verifier 不 agent 化** —— 守 flow-in-graph。
- **契約穩定性**:元素 9-11 與 3.2/4.3 的介面一旦定，後面 phase 只填內容;若 Phase 0 介面設計錯，
  後面會被迫改骨 —— 所以**介面設計是 Phase 0 最該 review 的部分**。
- **v27 legacy path** 維持現狀（fallback），不遷。
- **驗收 = 零回歸**。

---

## Roadmap

| Phase | 內容 | 對應本文 |
|---|---|---|
| **0** | 3-agent 骨架 + 契約 + registry（零行為改變） | §2、§6 |
| **1** | 監控平面納入（4 monitor agent 當 requester 接 Planner） | — |
| **2** | Episode / feedback channel + divergence → 讓 §3.2 語意裁判、§4.2 post-delivery 通 | §3、§4 |
| 3 | agent_knowledge 加 `class` 欄 + `block_doc_memos` 表 | 元素 9 |
| 4 | Planner fast-path / Builder 文件備忘 / Repair correction | 元素 10 |
| 5 | Supervisor 週期蒸餾 + curation | — |

### Phase 1 待決子問題（不阻擋 Phase 0）
monitor 觸發時:**(a) 跑既有 canned patrol**（低工）還是 **(b) 命令 Planner 動態建診斷 pipeline**（全願景）?

---

**簽收**:這版有補齊 agent 元素、Planner↔Builder 協作、Repair 接手/模式/執行了嗎?
符合預期請回覆「**開始開發**」,我從 Step 1 起手;要調整互動契約也直接說。
