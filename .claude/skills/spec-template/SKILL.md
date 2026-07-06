---
name: spec-template
description: 出任何開發 spec 前必用的兩層式模板 — 第一層 feature-first 對齊（無技術名詞），第二層才是實作細項。user 對齊第一層後才展開第二層。
---

# spec-template — 兩層式 Spec 模板

## When to invoke

**每一次**要產出 Tech/Product Spec 時（user 交辦新需求、架構設計、功能修改 —
即全域 CLAUDE.md 強制工作流的 Step 1）。沒有例外：修 bug 的小 spec 也用第一層
的精簡版（目標 + 1-2 個 feature 行 + 驗收）。

## 核心原則（2026-07-06 與 user 對齊的教訓）

第一版 spec 曾以工程師視角先行（schema/endpoint/migration 開頭），user 無法
review。**對齊的單位是「能力」不是「實作」**：先讓 user 用人話確認要做什麼、
為誰、怎麼驗，技術細節在第二層、且預設不進對齊討論。

## 第一層：對齊稿（一頁，先給這層、停下來等回饋）

```
## <這一波>的目標
一句話：做完之後，誰能多做什麼。

## Key Features
| # | Feature | 誰得到什麼 | 情境 before → after | 驗收 |
|---|---|---|---|---|
（每列四欄，禁止技術名詞 — 不出現 schema/endpoint/migration/flag/
 table 等字眼；「驗收」必須是 user 可以自己動手驗的一條）

## 不做的事
邊界清單 — 防止想像超出交付。

## 要你裁決的點
只列真正需要 user 選的，每點附建議選項。
```

規則：
1. 情境欄一律寫「現在怎樣 → 做完怎樣」的對比，不寫功能規格
2. feature 命名用人話（「失敗案查案」不是「trace forensics pipeline」）
3. 第一層結尾問句只問裁決點，不問「這份 spec 是否符合預期」以外的開放題

## 第二層：實作稿（第一層對齊完才展開）

```
## 逐 feature 技術設計
每個 feature 一節：資料/schema 異動、API、成本估計、風險。
只在 user 要求看、或某技術選擇需要 user 裁決時，才把該節攤進對話。

## 驗收清單總表
第一層每條驗收 → 具體操作步驟（指令/頁面/預期輸出）。

## 執行順序與分波
```

第二層產出後仍須依全域工作流等「開始開發」才動工。

## 交付時

依 feedback_acceptance_criteria_first：完工回報逐條對照第一層的驗收欄，
誠實標 PASS / 未觸發 / 部分（含原因），不得只報做了什麼。
