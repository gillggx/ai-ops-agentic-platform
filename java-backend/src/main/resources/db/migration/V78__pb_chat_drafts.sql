-- Chat 草稿暫存區 (2026-07-08): 對話建好的 pipeline 自動留一份，最近 10 個。
-- 輕量、獨立於 skills_v2 —— 沒有 role/automation/精靈，到「啟用」才升級成 Skill。
-- 汰換規則（在 service 端）：滿 10 個時刪最舊的「未標記」草稿；marked=true 永不汰。
CREATE TABLE IF NOT EXISTS pb_chat_drafts (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT      NOT NULL,
    name          TEXT        NOT NULL DEFAULT '',
    nl            TEXT        NOT NULL DEFAULT '',
    pipeline_json TEXT        NOT NULL,
    columns_json  TEXT        NOT NULL DEFAULT '{}',
    kind          TEXT        NOT NULL DEFAULT '',   -- thumbnail hint: spc_trend/bar/table/panel/pareto
    node_count    INT         NOT NULL DEFAULT 0,
    edge_count    INT         NOT NULL DEFAULT 0,
    marked        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pb_chat_drafts_user
    ON pb_chat_drafts (user_id, created_at DESC);
