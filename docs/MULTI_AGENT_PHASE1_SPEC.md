# Multi-Agent — 業務監控平面：Monitor Agents as Requesters【已往後排】

> **狀態:PARKED（2026-07-02）** — 依 user 決策,下一階段改為
> `MULTI_AGENT_OBSERVABILITY_SPEC.md`（agent 行為觀測 + Supervisor 調校迴路）。
> 本 spec 的業務監控內容保留,待觀測階段落地後再回來。
>
> Draft v1 · 2026-07-02。承接 `MULTI_AGENT_PHASE0_SPEC.md`（已交付,驗收 A1-A10 全過）
> 與 `AGENT_HARNESS_DESIGN.html` §6（指揮層:monitor 與 user 同位階）。
> 決策前提:D2 = 監控平面納入本 effort。
>
> **流程**:依 2026-07-02 議定,本 spec 內含驗收條款（§8）,與 spec 一起簽核;
> 開發完成後逐項回報同一份清單。

---

## 1. Context & Objective

**現況**:
- 監控偵測已存在:skills_v2 patrol（排程/事件 → pipeline → verdict → alarm）,
  V66 模型 + SkillScheduleService + SkillV2RunnerService 全部上線。
- Alarm 已有基本 explain（「為何觸發:量測值 vs 門檻」,commit 5dfdd61）。
- **缺的是**:alarm 之後的「診斷」是人工的。operator 看到 alarm,要自己開 builder
  查上下文（趨勢、分佈、同 recipe 其他機台…）。

**目標（Phase 1）**:讓 4 種 monitor（Tool / Process·站點 / APC / Recipe）成為
**與 user 同位階的 requester** —— 偵測到異常時,**像 user 一樣對 Planner 下需求**,
自動建一條「診斷 pipeline」,把結果掛回 alarm,operator 打開 alarm 就有 RCA 證據。

**一句話**:偵測維持 deterministic patrol（已有）;**Phase 1 新增的是「alarm →
自動指揮建置平面做診斷」這條邊**（AGENT_HARNESS_DESIGN §6 圖上 monitor → Planner 的綠色箭頭）。

---

## 2. 關鍵 Fork（本 spec 最大的待拍板）

monitor 觸發後要做什麼,兩條路 + 我的建議:

| 選項 | 做法 | 優點 | 缺點 |
|---|---|---|---|
| **(a) Canned** | alarm 後跑一條**預先綁定**的診斷 pipeline（照 skill 設定） | 零 LLM 成本、全 deterministic、立刻能做 | 診斷內容固定,不會因異常型態調整;每種異常都要人先建好診斷 pipeline |
| **(b) Dynamic** | alarm 後由 monitor-requester **組一句診斷需求 → 走 Planner→Builder 動態建** | 診斷貼合當下異常（帶 tool/chart/時窗上下文）;不用預建;吃到 build 平面全部能力 | 每次 alarm 花一次 build（GLM ~$0.1/次);需要節流與防迴圈 |
| **(c) 混合（建議）** | **偵測 canned、診斷 dynamic、皆可降級**:skill 若綁了診斷 pipeline 就跑 canned;沒綁 → dynamic 建;dynamic 失敗 → 只留 explain(現狀) | 漸進、可退、成本可控 | 實作面要管兩條路 |

**我的建議 = (c)**,理由:與平台哲學一致（deterministic 優先、LLM 只做必要的窄任務）、
向後相容（什麼都沒設定的 skill 行為不變）、成本有 cap。

> ▢ 待拍板 F1:走 (a) / (b) / (c)?

---

## 3. Architecture & Design

### 3.1 新元件:MonitorRequester（不是第 4 個 build agent）

```
python_ai_sidecar/agent_builder/agents/monitor_requester.py
```
- 套用 Phase 0 的 `RoleAgent` 契約（charter / model_cfg / tools / state_view / run）,
  註冊進同一個 registry —— **registry 從 3 個變 4 個**,證明 Phase 0 骨架的擴充性。
- 但它**不進 build graph**:它站在 build 平面**外面**,是 requester(跟 user 同位階)。
  它的 `run()` 做一件窄事:**把 alarm 上下文組成一句診斷需求(instruction)**。
- 4 種 monitor = **同一個 agent、4 個 scope profile**（tool / station / apc / recipe）,
  各 profile 差在:讀哪些 alarm 欄位、診斷需求模板、注入哪些 constraints。
  **不做 4 個類別**（避免 case-specific 碎片化,原則 0）。

### 3.2 資料流（dynamic 路徑）

```
skills_v2 patrol verdict=TRUE ──▶ AlarmEntity（既有）
        │  (既有 event fan-out 點)
        ▼
Java: alarm 建立後 POST sidecar /internal/monitor/diagnose {alarm_id}
        ▼
sidecar MonitorDiagnoseService（新,deterministic）:
  1. 讀 alarm + skill_run + trigger_payload（tool_id / chart / 時窗）
  2. 節流檢查（§3.4）— 不過就記 skipped_reason 結束
  3. MonitorRequester.run(view) → 產診斷 instruction（LLM 窄任務,一次呼叫）
  4. POST /internal/agent/build {instruction, skip_confirm=true, v30_mode=true}
     — agent-initiated build 是唯讀分析,免人工 confirm（§3.5 治理）
  5. 建成 → 執行 → 存 pipeline（draft）
  6. 回寫 alarm:diagnostic_pipeline_id + diagnostic_summary
        ▼
operator 開 alarm detail → 看到診斷圖表/表格 + 「在 Builder 開啟」連結
```

### 3.3 診斷需求的組成（MonitorRequester 的 view → instruction）

- **輸入 view**（compact,graph 組裝）:alarm(title/severity/equipment_id) +
  skill(nl/alarm_gate) + verdict 證據(量測值 vs 門檻) + trigger_payload + scope profile。
- **輸出 instruction**:模板骨架 + LLM 填空。例(tool scope):
  「EQP-03 的 xbar_chart 於過去 24h 觸發 OOC ≥2 次(實測 4)。請建診斷:
  (1) 該 chart 過去 7 天趨勢含管制線 (2) 同站其他機台同期對比 (3) 依 lot 分組的分佈」
- 模板是 **principle 式**（每 scope 一個,放 DB 或 constants,不寫 case 規則）。

> ▢ 待拍板 F2:instruction 組成先用「純模板(零 LLM)」還是「模板+LLM 填空」?
> 建議先純模板（成本 0、可測）,LLM 填空留給觀察到模板不夠用時。

### 3.4 成本與防迴圈（硬性,graph 管）

| 防護 | 規則 |
|---|---|
| 冷卻 | 同 (skill, tool) 對 N 分鐘內只診斷一次（建議 60m,env 可調） |
| 日上限 | 每日 dynamic 診斷 build ≤ M 次（建議 20,env 可調） |
| 防迴圈 | 診斷 pipeline **禁含 verdict/alarm block**（Builder constraints 注入 + 存檔前 lint 雙保險）→ 診斷永不再觸發 alarm |
| 防遞迴 | `/internal/monitor/diagnose` 產生的 build 標記 origin=monitor,其 alarm-hook 不再觸發診斷 |
| 降級 | dynamic 失敗(build fail / 超時) → alarm 保留現有 explain,記 diagnose_skipped_reason |

### 3.5 治理界線（沿用 cowork UI-handoff 原則）

- 診斷 build = **唯讀分析**（查資料、畫圖表）→ 可以 auto-run。
- 產出的 pipeline 一律存 **draft**,永不自動 activate、永不建 patrol/skill。
- 危險動作(刪/停/啟用)仍走 UI-handoff,monitor 平面不碰。

### 3.6 Schema 異動

- `alarms` 加 `diagnostic_pipeline_id BIGINT NULL` + `diagnostic_summary TEXT NULL`
  + `diagnose_skipped_reason TEXT NULL`（Flyway V69;prod 手動 psql）。
- skills_v2 的 canned 綁定（fork (a)/(c) 用）:`diagnostic_pipeline_id BIGINT NULL`。

---

## 4. 各 surface 改動

| Surface | 改動 |
|---|---|
| Java | alarm 建立後 fire-and-forget 呼叫 sidecar diagnose(不阻塞 alarm 寫入);alarms schema V69 |
| sidecar | MonitorDiagnoseService + MonitorRequester(agents 第 4 員) + 節流表(in-memory + DB fallback) |
| Frontend | alarm detail 加「診斷」區塊:ResultsBody 渲染診斷結果 + 開 Builder 連結;pending/skipped 狀態顯示 |

---

## 5. Step-by-Step Execution Plan

| Step | 內容 | 驗證 |
|---|---|---|
| 1 | V69 schema + Java fire-and-forget hook（feature flag `ENABLE_MONITOR_DIAGNOSE`,default OFF） | 單測 + flag off 全行為不變 |
| 2 | MonitorRequester(RoleAgent 第 4 員,純模板版) + 單測 | registry 4 員;view→instruction 快照測試 |
| 3 | MonitorDiagnoseService:節流 + 防迴圈 lint + build 呼叫 + 回寫 alarm | 單測(節流/迴圈/降級 3 路) |
| 4 | Frontend alarm detail 診斷區塊 | Playwright smoke |
| 5 | E2E:手動觸發一條 patrol → alarm → 自動診斷 → alarm detail 看到圖表 | 3 個 scope 各 1 案 |
| 6 | flag ON 灰度(先 1 條 skill)→ 全開 | 觀察 1 天成本/成功率 |

---

## 6. Edge Cases & Risks

- **Alarm 風暴**:全廠 fan-out 一輪可能 10+ alarm → 冷卻 + 日上限是硬要求,不是 nice-to-have。
- **診斷 build 失敗率**:v30 builder 對簡單診斷(趨勢/對比/分佈)成功率高(SLASH-17 17/17),
  但仍要降級路徑;失敗不影響 alarm 本體。
- **成本**:worst case = 日上限 M × ~$0.1 ≈ $2/日(GLM);explain-only 降級 $0。
- **simulator 資料 gap**:診斷查 7 天但 sim 只有部分資料 → 沿用 builder 現有 deficit 處理。
- **不做**（Phase 1 明確排除）:跨訊號 Monitor-Correlator(多 alarm 融合 RCA,未來)、
  monitor 自己的 memory(併入 Phase 3 memory class 一起做)、K8s 佈署變更。

---

## 7. 待拍板清單（簽核前要定）

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| F1 | 觸發後走哪條 | (a) canned / (b) dynamic / (c) 混合 | **(c)** |
| F2 | instruction 組成 | 純模板 / 模板+LLM 填空 | **先純模板** |
| F3 | 節流參數 | 冷卻 60m、日上限 20(env 可調) | 如左 |
| F4 | 診斷結果放哪 | alarm detail 內嵌(ResultsBody) / 獨立頁 | **alarm detail 內嵌** |
| F5 | 灰度起點 | 哪一條現有 patrol skill 先開 | 你指定 |

---

## 8. 驗收條款（Acceptance Checklist — 與 spec 一起簽核）

| # | 條款 | user 驗證方式 |
|---|---|---|
| B1 | flag OFF 時全系統行為不變(預設) | 部署後跑既有 patrol,alarm 流程無任何差異 |
| B2 | registry 有第 4 員 monitor_requester | `registered_names()` 含 4 個名字 |
| B3 | patrol 觸發 alarm 後自動產生診斷,掛回 alarm | 開 `/alarms` 任一新 alarm → detail 有診斷圖表區塊 |
| B4 | 診斷 pipeline 為 draft、無 verdict/alarm block | 診斷 pipeline 在 Builder 開啟,檢查 status=draft + 無 alarm 類 block |
| B5 | 冷卻生效 | 同 (skill,tool) 60m 內第二次 alarm → detail 顯示 skipped(cooldown) |
| B6 | 日上限生效 | 超過 M 次後 alarm 顯示 skipped(daily cap) |
| B7 | 防迴圈:診斷本身永不產生 alarm | 診斷跑完 alarms 表無新增 origin=monitor 的列 |
| B8 | 降級:diagnose 失敗時 alarm 本體不受影響 | kill sidecar 中途,alarm 仍正常建立含 explain |
| B9 | 3 scope E2E 各 1 案通過 | tool / APC / station 各觸發一次,診斷內容與 scope 相符 |
| B10 | 成本紀錄 | 每次診斷 build 的 token/cost 進 trace,可聚合日報 |
| B11 | SLASH-17 零回歸(build 平面未被弄壞) | strict ≥ baseline、cache 40–58% 維持 |

---

**簽核**:請先回答 §7 的 F1–F5(尤其 F1),並確認 §8 驗收條款是否要增刪。
定案後回覆「開始開發」,我依 §5 Step 1 起手。
