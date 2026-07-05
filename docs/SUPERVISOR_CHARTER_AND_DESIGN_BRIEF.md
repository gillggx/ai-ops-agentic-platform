# Supervisor Agent — 定位總綱 + 介面設計 Brief

> 2026-07-05 定稿討論版。前半是 Supervisor 的地位與職掌（產品事實），
> 後半是給 Claude Design 的介面設計需求。

---

## Part 1 — 地位與用途

### 一句話定位

**Supervisor 是平台的 SRE 兼知識策展人：它監督「執行體系（agents）」的健康與
「知識體系（knowledge & rules）」的品質，產出診斷與提案；它永遠只有提案權，
落地簽核永遠在人。**

### 為什麼升格（本次變更的核心）

今天「開發者人肉在做」的一批工作，本質是觀察與判斷，不是寫 code：

- 盯 SLASH/SMOKE 成績退步、rounds 變多、某類拒因暴增
- 盯成本異常（cache hit 掉、某 agent token 突然翻倍）
- 盯 provider 品質（例：2026-07-05 GLM 空回應率 33-45% 一整天）
- 判斷 budget 是否要調（react_rounds 用滿率）、flag 灰度是否健康

這些全部移交 Supervisor 自動化：**它產「有證據的提案」，人只做簽核**。
開發者保留的是 code 落地（git → deploy → gate）。

### 三個監督面

| 監督面 | 監督對象 | 資料來源 | 產出 |
|---|---|---|---|
| S1 執行健康 | Planner/Builder/Repair/Verifier 的表現 | episodes/steps、build traces、verifier 拒因統計、SMOKE/SLASH 成績 | 退步警報、根因診斷、調參提案 |
| S2 知識品質 | agent_knowledge / block docs / directives | 召回命中率、uses 計數、W1-W3 佇列、零召回事件 | PRUNE/PROMOTE/CORRECT/MERGE 提案 |
| S3 成本與資源 | LLM 花費、cache、provider 品質 | llm_usage、per-agent 成本、finish_reason 統計 | 成本異常警報、provider pin 建議 |

### 提案類型與簽核者（權責矩陣）

| 提案類型 | 例子 | 簽核者 | 落地方式 |
|---|---|---|---|
| 知識策展 | PRUNE 過時知識、PROMOTE W3 draft、MERGE 重複條目 | PE / IT_ADMIN | 簽核即落地（DB） |
| 文件修訂 | W2 doc memo 併入 block docs | PE | 簽核即落地（DB） |
| 設定調整 | 換 provider pin、調 budget、flag 開關 | IT_ADMIN | 簽核後由人執行（env/restart），Supervisor 追蹤驗證 |
| 程式級問題 | 「verifier 拒因 X 規則疑似誤殺」「prompt 原則 A 與 graph 行為衝突」 | 開發者 | 轉為 issue 型提案（附 trace 證據），走 git 流程 |

**硬規則（不可違反）：**
1. Supervisor 無落地權 — 一切變更經人簽核；危險動作只能從 authed UI 執行（cowork A+B 原則）
2. 提案必附證據鏈 — 每個提案連回 episodes / traces / 統計數字（▣ 系統事實），不接受純自述
3. code 不在職掌內 — 它可以「指出」code 問題，但修 code 是開發者的事
4. 提案會過期 — 新證據出現時舊提案自動 supersede，不留殭屍提案

### 與其他體系的關係（一張圖）

```
  執行體系 (A, code)          Supervisor              知識體系 (B, data)
  Planner/Builder/...   --episodes-->  觀察
  Verifier 拒因         --stats----->  診斷    --提案-->  提案收件匣 (人簽核)
  llm_usage/provider    --cost------>  報告               ├─ PE:  知識/文件
                                                          ├─ ADMIN: 設定
  SMOKE/SLASH 成績      --regression->                    └─ DEV: issue
```

---

## Part 2 — 介面設計 Brief（給 Claude Design）

### 要設計的東西

`/supervisor` 頁全面改版：從「單一報告頁」變成 **Supervisor 工作台**。
使用者是三種簽核者（PE / IT_ADMIN / 開發者），高頻動作是「看健康 → 審提案」。

### 資訊架構（四區）

1. **健康總覽（頂部 strip）** — 三個監督面各一組 KPI：
   - S1: 最近 N 次 build 成功率、平均 rounds、拒因 top1
   - S2: 知識條目數/本週召回命中率、待審佇列數（W2/W3/提案）
   - S3: 今日花費、cache hit %、provider 空回應率（今天這種 45% 的日子要一眼看到紅）
   - 任何 KPI 異常 → 直接錨到對應提案/報告

2. **提案收件匣（主區，核心）** — 依「我這個角色能簽的」預設過濾：
   - 提案卡 = **三段式**（沿用 Agent Console 語彙）：提案內容 / 為什麼（診斷）/ 依據（▣ 連到 episode·trace·統計，可點開）
   - 動作：核准 / 駁回（附一句理由）/ 擱置；批次核准同類低風險項
   - 狀態 chip：待審 / 已核准 / 已駁回 / 已過期（superseded — 顯示被哪個新提案取代）
   - 設定調整類提案核准後有「待人執行」中間態 + Supervisor 驗證結果回寫

3. **定期報告（digest）** — 週報/日報卡片流：退步偵測、divergence 摘要、
   成本趨勢；每個結論可展開證據；可一鍵轉成提案

4. **簽核紀錄（audit）** — 誰在何時核了什麼、落地結果、Supervisor 的事後驗證
   （提案 → 簽核 → 落地 → 驗證 四段生命週期，一列一案）

### 設計約束（必守）

- 語彙 tokens 與 Agent Console 共用（`#fbfbf9` 底 / 墨 `#211f1c` / 琥珀=風險 /
  綠=通過 / 紫=記憶·知識 / Planner 藍只給 plan 語意；mono 用於代號與數字）
- **禁 emoji**；幾何符號 ✓ ✕ ▲ ◆ ▣ ◈ 沿用既有語義（▣=系統事實、◆=記憶）
- 全字串走 i18n catalog（zh-TW source，4 語系）— 設計稿請標 key 不要只放死字
- 桌面優先（這是簽核工作台，不是側欄）；表格區 overflow 自理
- 證據優先原則：任何結論旁必有「依據」入口，比照 Console 三段式的可信度標記
  （▣ 系統事實 / △ 自述）

### 既有資產（設計時可引用）

- `/supervisor` 現有頁（v1 報告）、SUPERVISOR_WALKTHROUGH.html
- Agent Console 定稿（Agent_Panel 定稿.dc.html）的 tokens 與密度基準
- 已知待修 UX 債：PRUNE 提案顯示 target_ids 不友善、stale 提案不會 supersede
  （這次設計一併解）

### 不在範圍

- Supervisor 的判斷邏輯（後端）— 另案
- 行動版
- 知識編輯器本身（`/agent-knowledge` 既有，收件匣核准 W2 時跳轉即可）
