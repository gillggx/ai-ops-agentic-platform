-- V50 — 2026-05-21: 兩條 agent_knowledge 修 slash command audit 找到的 6/8 失敗。
--
-- Background (docs/slash-command-audit-2026-05-21.md):
--   實測 chat mode 14 個 / 快捷指令，8/14 fail。三個根因吃掉所有失敗：
--   (1) 無 alarm domain MCP → patrol-alarms / diag-alarm / diag-walkback 3 個 case
--       的 builder 卡在「猜 alarm MCP 名」迴圈 (24+ rounds, 全 fail)
--   (2) classify_advisor_intent 把帶具體 EQP / recipe / 參數名的 BUILD 請求誤判成
--       KNOWLEDGE → apc-corr / apc-recipe 進 advisor 路徑，沒建 pipeline 還幻覺虛構
--       block 名。
--
--   按 CLAUDE.md：不改 prompt 不改 agent flow，只能補 doc / memory。
--   agent_knowledge priority='high' 會被 plan_node 跟 classify_advisor_intent
--   都讀到（always-on 注入），所以這層適合放這種跨 surface 的 first principle。
--
-- Idempotent: WHERE NOT EXISTS by title.

-- ── Entry #1: Alarm 不在 builder scope ─────────────────────────────────────
-- Fixes: patrol-alarms / diag-alarm / diag-walkback (3 case)
INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'Alarm 查詢不在 pipeline builder scope — 不要試 mcp_call 猜 alarm 名',
       'Sidecar System MCP catalog **沒有任何 alarm 相關 MCP**。可用的 System MCPs 只有：
  - list_tools / get_simulation_status / get_process_info / get_process_summary
  - list_active_lots / list_steps / list_apcs / list_spcs
Alarm 資料住在 Java backend 的 /api/v1/alarms，**pipeline builder 取不到**。

⛔ 嚴禁的反模式（已多次浪費 20+ round 全 fail）:
  - 用 block_mcp_call 試 mcp_name=list_alarms / get_alarms / get_alarm /
    query_alarm / alarm_history / alarms / get_alerts / alerts — 全部不存在
  - 用 block_list_objects kind=alarm — 不支援
  - 把 process_history 的 spc_status=OOC 誤當「alarm」— 那是 SPC 層級狀態，
    不是 alarm 規則觸發的記錄

✅ 正確回應 — 三種情境分開處理:

  (A) user 純問 alarm 列表 / 狀態 / 觸發紀錄
      → 在 goal_plan_refused 直接說：
        「Pipeline Builder 目前無法查 alarm 紀錄，請改用左側選單 /alarms 頁面
         （Alarm Panel 提供 severity / status / 時間 filter）」
      → 不要試 build，省 20 round LLM token

  (B) user 想做「alarm 根因 = SPC/APC 證據」(e.g. diag-walkback、diag-alarm)
      → alarm 本身查不到，但其「等價語意」是 SPC/APC OOC events
      → 改 build：process_history → filter(spc_status=OOC) → 後續分析
      → 主動跟 user 確認：「我用 SPC OOC events 當 alarm proxy 可以嗎？」

  (C) user 想做「alarm 觸發 skill」(skill_step_mode)
      → 這條 path 由 java-scheduler EventDispatchService 自動觸發，
        builder 端只負責 build skill 的內容 pipeline (取 SPC/APC + step_check)。
      → trigger 本身不需要 alarm MCP；不要在 pipeline 內試查 alarm 列表。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (
  SELECT 1 FROM agent_knowledge WHERE title = 'Alarm 查詢不在 pipeline builder scope — 不要試 mcp_call 猜 alarm 名'
);

-- ── Entry #2: Compare / correlation 帶具體 ID = BUILD 不是 KNOWLEDGE ──────
-- Fixes: apc-corr / apc-recipe (2 case)
INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'Intent classification — 帶具體 ID 的 compare/correlation/change 是 BUILD 不是 KNOWLEDGE',
       'classify_advisor_intent 5-bucket 分類規則 — 避免把可建 pipeline 的請求誤丟給 advisor。

⛔ 已知誤判 case:
  - 「找 EQP-01 APC etch_time_offset 跟 SPC xbar OOC 的相關性」
    → 被誤判 KNOWLEDGE，走 advisor 給概念說明，沒建 pipeline
  - 「EQP-01 在 recipe RECIPE_A 切到 RECIPE_B 後 APC 參數有沒有變化？」
    → 被誤判 KNOWLEDGE，advisor 還幻覺虛構 `block_query_equipment_data` /
      `block_trend_analysis` 兩個不存在的 block

✅ 判別原則（看 instruction 有沒有「具體 ID」）:

  如果 instruction 帶任一具體 ID:
    - 機台 ID (EQP-01, EQP-02, ...)
    - Step ID (STEP_001, STEP_003, ...)
    - Lot ID (LOT-0234, ...)
    - Recipe ID (RECIPE_A, ...)
    - APC 參數名 (etch_time_offset, rf_power_bias, ...)
    - SPC chart 名 (xbar_chart, r_chart, ...)
    - Alarm # / Alert ID

  且動詞屬於以下任一:
    - 比較 / compare / 對比 / vs
    - 相關性 / correlation / 關聯 / 連動
    - 變化 / 改變 / 漂移 / change / drift / shift
    - 倒推 / trace back / 根因 / root cause
    - 找 / 列出 / 看 / show / list (帶具體篩選條件)

  → **BUILD intent** — 走 graph_build 建 pipeline，不要進 advisor

⛔ KNOWLEDGE 僅限**純概念**問題（不帶具體 ID）:
  - 「什麼是 EWMA-CUSUM？」「Cpk 怎麼算？」「SPC 跟 APC 差在哪？」
  - 「線性回歸 R² 多少算顯著？」「OCAP 是什麼？」

✅ 邊界 case 判決:
  - 「比較 SPC 跟 APC」(無 ID) → KNOWLEDGE（純概念）
  - 「比較 EQP-01 SPC 跟 APC」(帶 ID) → BUILD
  - 「相關性怎麼算？」→ KNOWLEDGE
  - 「找 EQP-01 兩個參數的相關性」→ BUILD
  - 「Recipe 切換會影響 APC 嗎？」(理論) → KNOWLEDGE
  - 「EQP-01 在 RECIPE_A → RECIPE_B 切換後 APC 變化」(實際) → BUILD

📢 advisor 拒絕 build 請求時，明確說：
  「這個請求需要實際資料查詢，請點 ✅ 確認 pipeline 計畫」— 不要寫成
  「我的角色只回答概念問題」這種推卸式 reply（用戶會反感）。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (
  SELECT 1 FROM agent_knowledge WHERE title = 'Intent classification — 帶具體 ID 的 compare/correlation/change 是 BUILD 不是 KNOWLEDGE'
);
