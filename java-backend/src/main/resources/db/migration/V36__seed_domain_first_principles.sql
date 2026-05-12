-- V36 — Seed 4 semiconductor "first principle" knowledge entries.
--
-- Background (2026-05-12):
--   User reported that build agent generated wrong pipelines (filtered SPC
--   by tool_id + lot_id, returning 1 data point instead of trend). Root
--   cause: agent had no domain understanding that SPC charts are
--   station-level aggregations across tools/lots — that's a half-step
--   above what individual block descriptions encode.
--
--   Existing agent_knowledge entries (id 1-12) cover tactical rules (OCAP,
--   WECO, Cpk thresholds, ...). Missing the structural "where data live"
--   first principles. These 4 entries codify the cross-cutting domain
--   semantics so plan_node retrieves them as context before drafting plans.
--
--   Per CLAUDE.md description-driven principle: NOT in block descriptions
--   (those describe the block, not the domain) and NOT in system prompts
--   (those would be hardcoded). Lives in agent_knowledge, retrievable
--   via pgvector cosine similarity once the sidecar backfill embeds them.
--
-- Idempotent guard: skip if any title already exists.

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'SPC chart 是「站點 (step)」層級的管制圖',
       'SPC (Statistical Process Control) charts 在半導體業界是站點層級的 quality control charts。每張 chart 監測一個站點的某個量測 (e.g. CD_Mean at STEP_001)，data point 來自**所有經過該站點的 lots / wafers**，跨機台、跨 lot 累積。

當 pipeline 要顯示「SPC chart trend」（業界 SPC 標準語意）：
  - block_process_history 的 filter **只用 step**（不要加 tool_id / lot_id），time_range >= 7d
  - 想做 tool-stratified 比較才在後續 block_groupby_agg by toolID
  - 想做 lot-level 比較才 group by lotID

當 pipeline 要顯示「某次 OOC event 當下的 SPC 12 chart snapshot」：
  - 那是 1 個 event 的多 chart 量值，**不是** trend
  - 三個 ID filter (tool/lot/step) 都填，輸出 1 row × 12 chart values

常見誤用：user 講「顯示該 SPC chart trend」結果 LLM 同時 filter tool+lot+step + sort limit=1 → 只有 1 point，圖看起來空。這 prompt 的本意通常是站點層級的 trend，不是 single-event snapshot。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = 'SPC chart 是「站點 (step)」層級的管制圖');

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'APC 是「recipe」層級的 run-to-run 補償',
       'APC (Advanced Process Control) 是 recipe-level 的 feedback/feedforward 補償機制。APC 模型按 recipe + step 組合定義（同 recipe 跑在不同 tool 上共用 APC 模型），每個 lot 跑完後依量測結果調整下一 lot 的 process parameters。

當 pipeline 要分析「APC 補償的時序趨勢」：
  - filter 用 recipe_id 或 apc_id（block_process_history 的 object_name=APC）
  - 可選 加 tool_id 做 tool-stratified 比較
  - **不要只用 tool_id**，因為同 tool 跑多個 recipe，APC 訊號會混在一起
  - 關注欄位：apc_fb_correction（feedback 量）/ apc_ff_correction（feedforward 量）/ apc_drift_score

跟 SPC 的對比：SPC 是「站點層級的 quality 量測」，APC 是「recipe 層級的 process 補償」。兩者 cross-cutting 但語意不同。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = 'APC 是「recipe」層級的 run-to-run 補償');

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'FDC 是「tool + chamber」層級的故障偵測',
       'FDC (Fault Detection & Classification) 是 tool + chamber 層級的多變量故障偵測。fault signatures 跟特定 chamber 強相關（chamber 老化、漏氣、partial pressure drift 等），所以 FDC trend / classification **必須**帶 tool_id + chamber_id 才有意義。

當 pipeline 分析「FDC 異常」：
  - filter 用 tool_id + chamber_id 雙欄位
  - 單看 tool 層級會被多 chamber 訊號平均掉，看不出哪個 chamber 出問題
  - 關注欄位：fdc_classification (NORMAL/WARNING/FAULT) / fdc_fault_code / fdc_contributing_sensors

跟 SPC 完全不同的語意：
  - SPC 可跨 tool 累積（quality metric 不分機台）
  - FDC **不能**跨 tool 比較 — 每台機台、每個 chamber 健康狀況獨立

常見誤用：user 說「分析 FDC 異常」LLM 寫個 group by 全 tool 平均 → 等於把好機台跟壞機台拌在一起，異常被淹沒。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = 'FDC 是「tool + chamber」層級的故障偵測');

INSERT INTO agent_knowledge (user_id, scope_type, title, body, priority, source, created_at, updated_at)
SELECT 1, 'global',
       'Recipe drift = 跨 recipe_version 的量測偏移',
       'Recipe drift 指 recipe 設定（gas flow / RF power / etch time / temperature 等）跨版本變動所造成的量測偏移。判斷 recipe drift 需要：
  - recipe_id + recipe_version 雙欄位 filter（同 recipe_id 不同 version）
  - 對比同 recipe_id 跨 version 的 SPC / APC 量值
  - **不要** 只看單一版本內的 variation — 那是 noise (within-version)，不是 drift

事件來源：RECIPE_VERSION_BUMP event (event_types id=19)。觸發後該 recipe 的下批 lots 量值要跟前版做對比。

跟「lot-to-lot variation」的差異：lot-to-lot 是 within-recipe 的 noise；drift 是 between-recipe-version 的 mean shift。混為一談會把正常的 lot variation 誤判為 drift。',
       'high', 'manual', now(), now()
WHERE NOT EXISTS (SELECT 1 FROM agent_knowledge WHERE title = 'Recipe drift = 跨 recipe_version 的量測偏移');
