# Design Brief：Agent Console（AI Agent Panel 第二分頁重造）

> 交接對象：Claude Design。互動 mockup（v2，含三段式內容實例）：
> **https://gillggx.github.io/ai-ops-agentic-platform/AGENT_CONSOLE_MOCKUP.html**
> mockup 是 PM 畫的資訊架構示意，**視覺請重造，不要被它錨定**。

## 1. 背景與問題

AIOps 平台有一個 400px 寬的 AI Agent 側欄，兩分頁：「對話」與「Console」。
Console 目前是舊架構（9-Stage Pipeline）的流程卡，其中 Stage 3-6 的事件源已拆除，
卡片永遠空白，功能上已死。同時 agent 系統已 multi-agent 化
（Planner 規劃 / Builder 建構 / Repair 修復 / Verifier 裁決）且具記憶系統
（agent 會引用與寫入記憶）——但使用者完全看不到這些內部運作。

**產品定位一句話：對話 tab 看「事」（任務結果），Console 看「agent」（內部運作）。**
最終目的：使用者**理解 agent → 修正它 → 補給它需要的 knowledge**。

## 2. 設計目標（用戶 10 秒內要能回答的三個問題）

1. **現在誰在動？** 三個 agent 哪個在思考/行動、進行到第幾 phase 第幾輪
2. **它為什麼這樣做？** 每一步的決定、理由、依據（含引用了哪條知識的哪一句）
3. **哪裡需要我？** 哪一步 agent 在沒有知識支援下摸索（可以「教它」）

## 3. 已定案、不需重想的

- **資訊架構四區塊**：Agent 狀態列 → 活動流（三段式）→ 記憶效應 → 成本
- **每步三段式內容**：`決定`（做了什麼）/ `理由`（一行中文口語）/ `依據`（徽章）
- **依據的兩級可信度**（關鍵設計語彙）：
  - `▣ 系統事實` — verifier 裁決、實測 rows、user 勾選（機器驗證過，實線）
  - `⚠ agent 自述` — 模型自己講的理由，可能事後編（虛線；user 修正時優先質疑）
  - `◈ 引用` — 顯示被引用記憶的 **How-to-apply 句**，不只編號
- **分工**：Console 只看本次 session；歷史深潛交給 `/agent-activity` 頁
- **Agent 色彩錨點**（全產品已用）：Planner 藍 / Builder 綠 / Repair 琥珀 / Verifier 灰 / 記憶紫

## 4. 設計課題（核心委託）

| # | 課題 | 說明 |
|---|---|---|
| D1 | **400px 密度戰爭** | 一次 build 20-60 條三段式事件。怎麼做到「掃一眼知進度、想看才有細節」？折疊策略/每 phase 只展最新/虛擬滾動＋錨點——本案最難的題 |
| D2 | **「活著」的感覺** | build 進行中 vs 閒置的視覺差；agent idle → 思考 → 行動 → 交棒的狀態轉場（注意 `prefers-reduced-motion`）|
| D3 | **失敗的分級語言** | Verifier REJECTED（日常）/ Repair 介入（注意）/ handover（壞消息）三級，誠實但不製造焦慮 |
| D4 | **記憶的因果感** | 「引用 #82」與「寫入 W1」是本產品最獨特的時刻（agent 在學習）。怎麼讓它有存在感？「新蒸餾記憶第一次被引用」值得一個 moment |
| D5 | **空狀態** | 沒有 build 時顯示什麼？要能自我解釋「這裡是什麼」 |
| D6 | **三段式的排版** | 決定/理由/依據 + 兩級可信度徽章在窄欄的層次（mockup 有內容實例，排版請重造）|
| D7 | **「教它」時刻** | 召回 0 筆的步驟高亮 + 一鍵開知識新增（自動帶入 block/phase/指令情境）。這是「看見 → 理解 → 補知識」閉環的入口，值得醒目但不打斷 |

## 5. 限制

- 寬度 380-400px 基準（可 resize 至 50vw）
- 淺色主題、系統字體；**全產品禁 emoji**（文字標記/幾何圖形替代）
- 事件 streaming 逐條浮現，非一次渲染
- 資料源：區塊 1/3/4 全用既有 SSE 事件；D6 的「理由」需一項輕量後端增補（工具呼叫 schema 加 `reason` 欄，10-20 tokens/步）——設計不受此限，照三段式設計即可

## 6. 內容實例（實際 build 的一步，設計時用這種真實密度）

```
BUILDER · p1 · round 1
決定   add_node process_history(EQP-01, 7d)
理由   「這 phase 要原始資料，這是唯一的歷史資料來源」  ⚠ agent 自述
依據   ◈ #82 tool_id/lot_id/step 三擇一 → 所以帶了 tool_id
結果   ▣ 59 rows（系統實測）
```

「教它」時刻（召回 0 筆）：

```
BUILDER · p4 · round 3                                    ⚠
決定   set_param 按日聚合（groupby day）
理由   「要每日均值趨勢，先按天分組」  ⚠ agent 自述
依據   ✕ 這一步召回 0 筆相關記憶
       ┌──────────────────────────────────┐
       │ agent 在沒有知識支援下摸索中        │
       │ 你知道怎麼做對嗎？  [教它 →]        │
       └──────────────────────────────────┘
```

## 7. 驗收（設計稿對答案）

- [ ] 進行中 session：10 秒說出「Builder 在 p3 第 2 輪、剛被拒過一次」
- [ ] 40+ 條三段式事件在 400px 可掃讀、無水平捲動
- [ ] 失敗三級視覺可區分
- [ ] `▣ / ⚠ / ◈` 三種依據一眼可辨
- [ ] 「教它」時刻醒目但不打斷流程
- [ ] 空狀態自我解釋；reduced-motion 功能不減

## 8. 參考資料

- 互動 mockup v2：https://gillggx.github.io/ai-ops-agentic-platform/AGENT_CONSOLE_MOCKUP.html
- 現有產品卡片語言（實機截圖）：https://gillggx.github.io/ai-ops-agentic-platform/UI_CARDS_SHOWCASE.html
- 各 agent 運作流程：https://gillggx.github.io/ai-ops-agentic-platform/AGENT_OPERATIONS_FLOW.html
- Supervisor / 記憶系統：https://gillggx.github.io/ai-ops-agentic-platform/SUPERVISOR_WALKTHROUGH.html
