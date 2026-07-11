-- V85 (2026-07-11): 工作與畫面非同步 — Agent Tasks + Session rich history
--
-- 1. agent_tasks: 背景工作（build / skill_run）的持久化狀態。執行本體在
--    sidecar in-process（asyncio task + 記憶體事件緩衝）；此表負責
--    (a) 跨 sidecar 重啟的狀態可見性 (b) 完成後的 terminal events
--    （done 卡 + 圖卡 payload）供離線期間完成的工作回放。
CREATE TABLE IF NOT EXISTS agent_tasks (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,              -- 'build' | 'skill_run'
    chat_session_id  TEXT NOT NULL,
    user_id          BIGINT,
    status           TEXT NOT NULL,              -- running | finished | failed | interrupted
    goal             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    -- 從 pb_glass_done 起的收尾事件（JSON array，含圖卡）— 客戶端回放用
    terminal_events  TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_session
    ON agent_tasks (chat_session_id, created_at DESC);

-- 2. rich history: 對話的完整訊息串（含圖卡，client 端 ChatMessage[] 原樣
--    JSON）。localStorage 版本的 server 備份 — 跨裝置還原用。
ALTER TABLE agent_sessions ADD COLUMN IF NOT EXISTS rich_history TEXT;
