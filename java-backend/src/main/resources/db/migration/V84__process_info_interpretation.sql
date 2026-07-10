-- V84 (2026-07-11): get_process_info 判讀紀律 + 移除不存在工具的引用
--
-- Prod incident: Coordinator 對 APC 裸數值（model_r2_score 0.943 等）下了
-- 「很高／合理範圍」的經驗斷言，並向使用者推薦 description 裡提到、但平台
-- 根本不存在的 query_object_timeseries。修法遵循「MCP description 是唯一
-- 文件來源」：文件本身要正確、要自帶判讀紀律，不是往 prompt 加 case rule。

-- 1. 移除不存在的工具引用（description 曾指向 query_object_timeseries，
--    該工具從未建成 MCP）
UPDATE mcp_definitions SET description = replace(description,
  '- 要看單一參數 30+ 天的長期時序 → 用 query_object_timeseries',
  '- 要看單一參數的長期時序 → 一樣用這個，帶 since=''30d'' 拉多筆自行對比'
  || '（平台沒有獨立的 timeseries 工具，不要向使用者推薦不存在的工具名）')
WHERE name = 'get_process_info';

-- 2. 附上判讀紀律（哪些欄位可引用為判定、哪些是裸數值）
UPDATE mcp_definitions SET description = description ||
  E'\n\n== 判讀紀律 ==\n'
  || E'APC.parameters / DC 感測值都是裸數值，沒有 status / spec 欄位。\n'
  || E'可引用為「判定」的欄位只有：spc_status（PASS|OOC）、SPC.charts[].is_ooc、\n'
  || E'EC 項目的 ALERT 狀態。要評 model_r2_score / stability_index 這類指標\n'
  || E'「正常與否」，必須先帶 since=''30d'' 拉同 toolID 歷史多筆算分佈再對比；\n'
  || E'沒做對比就只陳述數值並說明「缺基準無法判讀」——不得用經驗寫成斷言。\n'
WHERE name = 'get_process_info';

-- 3. emoji 清理（全站禁 emoji／類 emoji，V31 時代殘留）
UPDATE mcp_definitions SET description =
  replace(replace(description, '== ✨ ', '== '), '⚠ ', '[注意] ')
WHERE name = 'get_process_info';

-- 4. 標準 Skill 說明書同步（process-info-mcp）
UPDATE agent_skills SET body = body ||
  E'\n4. 就數據說話：APC.parameters／DC 都是裸數值，沒有 status／spec 欄位。可引用的判定\n'
  || E'   依據只有 spc_status（PASS|OOC）、SPC.charts[].is_ooc、EC 項目的 ALERT。要評\n'
  || E'   model_r2_score、stability_index 這類指標正常與否，先帶 since=''30d'' 拉同機台\n'
  || E'   歷史多筆算分佈再對比；沒對比就只陳述數值＋「缺基準無法判讀」，不要用經驗下\n'
  || E'   「很高／正常／合理範圍」這種斷言。\n',
  updated_at = now(), updated_by = 'V84'
WHERE name = 'process-info-mcp';
