-- V87 (2026-07-12): Coordinator 補能力 — Chat 草稿 / 跨對話搜尋 / 知識管理
--
-- 四段對話實測抓到的缺口：
--  1.「草稿」二義：agent 只看得到 skills_v2 draft，看不到左欄 My Drafts
--  2. 規則/偏好只能新增，不能刪/停用
--  3. 刪草稿數量對不上（同 1）
--  4. 跨對話查不到（「我之前不是請你…」）

-- 1. 授權四個新 builtin（is_internal = 對內給 Coordinator）
INSERT INTO mcp_capability_settings (capability_key, kind, is_public, updated_by, is_internal)
SELECT k, 'builtin', true, 'V87', true
FROM (VALUES ('list_chat_drafts'), ('show_chat_draft'),
             ('search_past_conversations'), ('manage_knowledge')) AS t(k)
WHERE NOT EXISTS (
  SELECT 1 FROM mcp_capability_settings s WHERE s.capability_key = t.k);

-- 2. domain-skill-management 說明書：兩種「草稿」講清楚
UPDATE agent_skills SET body = body ||
  E'\n## 「草稿」有兩種——先分清楚使用者指哪個\n'
  || E'- **Chat 草稿暫存區（My Drafts）**：對話建圖自動暫存的 pipeline（介面左欄，上限 10）。\n'
  || E'  使用者說「草稿／我的草稿」**預設指這個** → 用 list_chat_drafts 列、show_chat_draft 出草稿卡\n'
  || E'  （試跑/啟用/刪除都在卡上由使用者按，你不要代按）。\n'
  || E'- **Skill 草稿**：skills_v2 裡 status=draft 的 skill → list_skills_v2。\n'
  || E'  只有使用者明確講「draft 狀態的 skill」才是這個。\n'
  || E'不確定指哪種就先 list_chat_drafts；兩邊數量不同是正常的，不要混著報。\n',
  updated_at = now(), updated_by = 'V87'
WHERE name = 'domain-skill-management';

-- 3. knowledge-rules 說明書：改刪 + 偏好記錄的誠實邊界
UPDATE agent_skills SET body = body ||
  E'\n## 刪除／停用規則\n'
  || E'用 manage_knowledge（action=delete|deactivate, knowledge_id 從 list_agent_knowledge 拿，\n'
  || E'title 一併帶給確認卡顯示）。會出確認卡，使用者按確認才生效——不要說「我沒有工具」。\n'
  || E'\n## 記錄偏好時要誠實\n'
  || E'偏好（如圖表樣式）記錄後是否真的套用，取決於該偏好有沒有進到對應流程（建圖偏好會、\n'
  || E'閒聊偏好只影響回話）。不確定就說「已記下，下次建圖時會帶入驗證」，不要保證「一定自動套用」。\n',
  updated_at = now(), updated_by = 'V87'
WHERE name = 'knowledge-rules';
