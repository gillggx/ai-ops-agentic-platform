-- V82 (2026-07-10): 標準 Skill — named instruction packages the Coordinator
-- loads on demand (Anthropic Agent-Skills pattern). One row = one manual:
-- when_to_use goes into the agent's system-prompt index; body is fetched via
-- the load_skill tool only when the request matches. Editable in GUI — the
-- manual is data, not code.
-- NOTE: Flyway is disabled in prod — apply manually via psql.

CREATE TABLE IF NOT EXISTS agent_skills (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(64)  NOT NULL UNIQUE,
    when_to_use VARCHAR(300) NOT NULL,
    body        TEXT         NOT NULL,
    enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
    updated_by  VARCHAR(64),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Seed: the first standard skill — alarm handling (能力包的使用說明書).
INSERT INTO agent_skills (name, when_to_use, body, updated_by)
VALUES (
  'alarm-handling',
  '使用者要查詢、摘要、統計、認領、處置或結案「告警 / alarm」時',
  E'# alarm-handling — 告警查詢與處理\n\n'
  E'## 工具與時機\n'
  E'- query_alarms(equipment_id?, since_hours?, status?, severity?, limit?)：查歷史+處理狀況。例「EQP-07 過去24小時的alarm」→ query_alarms(equipment_id=EQP-07, since_hours=24)。\n'
  E'- get_alarm_stats(since_hours?)：統計（哪台最多、by_status、ack_rate）。「哪台告警最多／處理狀況如何」先用這個。\n'
  E'- get_alarm_detail(alarm_id)：單筆完整診斷（AI 綜整 + evidence）。下處置前必看。\n'
  E'- list_alarms()：現在的整體戰況（clusters + KPI），不帶過濾條件時用。\n'
  E'- 動作：ack_alarm(alarm_id 或 equipment_id 整台)、dispose_alarm(alarm_id, release|hold|scrap|rerun, reason)、resolve_alarm(alarm_id，需 ADMIN/PE)。\n\n'
  E'## 摘要格式\n'
  E'用 markdown 表格（ID／標題／嚴重度／狀態／時間），表後給 2-3 個重點：未認領數、重複 pattern、建議下一步。\n\n'
  E'## 動作規範\n'
  E'1. 所有動作一律出確認卡，使用者按了才生效；出卡後只回一句「確認卡在上面了」。\n'
  E'2. dispose 前先 get_alarm_detail 看 evidence 並確認原因；scrap 不可逆，要特別提醒。\n'
  E'3. 批次認領前先 query_alarms 把清單列給使用者看。\n\n'
  E'## 分界\n'
  E'- 查詢／處理：用上面的工具直接回答，**不要**為了查資料建 pipeline。\n'
  E'- 「自動跑／定期巡檢／幫我盯著」：用 search_skills 找現成 Domain Skill → 有就 invoke_skill 或帶去設自動化；沒有才提議建一條（會出計畫卡）。',
  'system'
) ON CONFLICT (name) DO NOTHING;
