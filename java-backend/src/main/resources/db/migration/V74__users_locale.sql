-- i18n P3 (2026-07-05): per-user UI locale (zh-TW / zh-CN / en / ja).
-- Cookie NEXT_LOCALE is the per-browser cache; this column is the
-- cross-device source of truth. NULL = never chosen (default zh-TW).
ALTER TABLE users ADD COLUMN IF NOT EXISTS locale VARCHAR(8);
