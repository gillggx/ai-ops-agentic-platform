# 待驗證清單 — 2026-07-06 → 07-08 交付

平台：<https://aiops-gill.com>　·　驗證頁：`/agent-activity`、`/skills`、`/supervisor`、Chat panel

勾選方式：驗過打勾。有問題就把該列的「預期 vs 實際」記在後面。

---

## A. Coordinator 分診制（調圖秒改／不重建）

- [ ] **A1 調圖秒改快路** — chat 建好一張 SPC 圖後，接著說「拿掉區帶」「軸標籤改成 X」「提示加 recipe」
  → 預期：~7s 內原圖更新，**不會**跳新的 plan 確認卡、不重抓資料
- [ ] **A2 source cache** — 同一輪 build 多節點共用來源
  → 預期：Agent Activity 時間軸出現 `source_cache_stats`（1 fetch + N reuse）
- [ ] **A3 G3 兜底** — 講一句模稜兩可的「改一下」
  → 預期：不會做出錯圖；退回正常流程（最壞是重建，不會壞掉）

## B. Agent Activity 可讀性 + Topic

- [ ] **B1 Topic + user 列首** — 開 `/agent-activity` 點任一筆
  → 預期：最上方 Topic 卡顯示原始 prompt；下指令的 user 顯示在第一個
- [ ] **B2 時間軸人話** — 看某筆的時間軸
  → 預期：不再是 `llm_usage`；改為「選了 block_X／查了 Y 文件／驗收拒絕原因／修理工單」等中文動作句
- [ ] **B3 MetaBar 不堆疊（修 3 次的那個）** — 連續點不同 episode 切換
  → 預期：**永遠只有 1 條** MetaBar，不會殘留前一條

## C. Chart 樣式＝block 參數（agent + cowork 可調）

- [ ] **C1 agent 可調樣式** — chat 對圖說「顯示柱上數值」「線改虛線」「加圖例」
  → 預期：圖套用；走秒改快路
- [ ] **C2 tooltip 欄位** — 「提示改成顯示 lot_id 和 recipe」
  → 預期：tooltip 換欄；給不存在欄名時**明確報錯**並列可用欄
- [ ] **C3 文件對齊** — Builder 開任一 chart block 的 docs
  → 預期：description 有樣式參數說明（原則式，非 case 清單）

## D. 真 Skill 化（參數化 inputs + 說明書）　`issue#3`

- [ ] **D1 存為 Skill 精靈** — chat 建完 pipeline，點卡片右下「存為 Skill」
  → 預期：跳**參數化精靈**（source 身分參數候選、預設全勾）
- [ ] **D2 說明書草擬** — 精靈第 2 步點「用 AI 草擬」
  → 預期：Haiku 產 use_case／when_to_use／tags，可編輯
- [ ] **D3 動態 inputs** — 存完後開 `/skills/[slug]`
  → 預期：pipeline 的 tool_id 等變成 `$name` 宣告式 input，呼叫時可換
- [ ] **D4 agent 搜得到** — 存完後在別的對話叫 agent 用這個 skill
  → 預期：搜尋列得到（chat 存的 skill 也進得了檢索）

## E. Cowork（外部 Claude Desktop）開放　`requirement#1`

- [ ] **E1 看 agent activity** — Claude Desktop 呼叫 `list_agent_activity` / `get_agent_activity`
  → 預期：回真 episode（後端已 curl 驗過，含 EQP-07「超過 3 次 OOC」案，199 steps）
- [ ] **E2 治理 propose-only** — cowork 呼叫 `propose_knowledge` / `propose_doc_revision`
  → 預期：進 Supervisor 佇列（`source='cowork'`），**不自動核准**，要人在 `/supervisor` 審
- [ ] **E3 參數化／調圖／說明書** — cowork 呼叫另 3 個新工具（`parameterize_pipeline`／`patch_chart_style`／`draft_skill_doc`）
  → 預期：能正常產出（手感待實測）

## F. Table 大資料量效能

- [ ] **F1 大表不卡** — 開一個大資料量的檢視（DataResultView／DataPreview）
  → 預期：只渲染前 100 筆、顯示 totalRows，不卡
- [ ] **F2 全量下載** — 點 CSV 下載鈕
  → 預期：得到**完整**資料（非只 100 筆）
- [ ] **F3 畫圖用全量** — try-run 畫圖
  → 預期：圖用全部資料，不受 100 筆限制影響

## G. 模型／通道

- [ ] **G1 LLM 次數／延遲** — 任一 build 完看 meta/console
  → 預期：顯示累積 LLM call 數 + 平均延遲
- [ ] **G2 效能報告** — 開 `docs/MODEL_PERF_ANALYSIS_2026_07.html`
  → 預期：單 vs 多 agent × 6 模型的 SLASH-17 對照
- [ ] **G3 已切 Sonnet-5** — 現在跑一個 build
  → 預期：走 Sonnet-5 + adaptive thinking(high)；品質最佳、成本較高，可隨時回退 Haiku（`.env.bak-haiku-*`）

---

## 尚未修（backlog，兩個都在 rebuild flow，建議一起做）

- [ ] **ISSUE#1** 增量修改被重跑 —「有超過 3 次 OOC 就要 alarm」在已建好的 pipeline 上，結果重跑整條
  → 修向：G1 route `logic_extension` → M2 `insert_phase`（v1 暫排除）把 delta phase 接到現有 canvas
- [ ] **ISSUE#2** 重建時 Lite Canvas 空白 — 重新設計時 canvas 看不到任何 block
  → 修向：`start` 事件強制切回 Canvas 視圖 + reset 時序

---

### 相關參考文件

- `docs/MULTI_AGENT_PROGRESS.html` — 進度總表（07-08 更新）
- `docs/CHART_STYLE_SPEC_VISUAL.html` — 11 種圖樣式 before/after
- `docs/MODEL_PERF_ANALYSIS_2026_07.html` — 模型效能分析
- `docs/LLM_CHANNEL_CONFIG_GUIDE.html` — OpenRouter / AWS Bedrock 設定

### 對應 commit（2026-07-06 → 07-08）

| 區 | commit |
|---|---|
| plan-gate / MetaBar | `23bfaf77` `7a5825df` |
| table 效能 | `639de1cb` |
| LLM thinking/cache + 效能報告 | `c69fbecf` `e51cd1aa` `f9d6ef06` `87997731` `bad0942f` |
| Agent Activity Topic + 可讀性 | `18edf13e` `c4054585` `c6c33e2d` `79460182` |
| chart 樣式 | `a56c4478` `c74172de` `4410094b` `23b8a346` `88ab1d50` |
| Coordinator 分診制（三波） | `9ad6a3c5` `8aab1695` `281a62ca` `dd1eee2b` `3ce49a2d` `bad70785` `62f82301` |
| 真 Skill 化 | `ea149d08` `3b89e333` `b5c24904` `35f2eb88` |
| cowork 開放 + 看 activity | `bc3f9f6a` `06afaa5b` |
