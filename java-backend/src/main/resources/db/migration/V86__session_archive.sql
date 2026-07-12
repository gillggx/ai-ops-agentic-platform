-- V86 (2026-07-12): 對話保留政策 — 近期上限 5 則 / 打包歷史上限 10 則。
-- 開新對話（第一次寫入 title）時超過 5 則 → 最舊自動打包（archived_at 設值、
-- rich_history 清空只留文字）；打包歷史超過 10 則 → 最舊刪除。
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
