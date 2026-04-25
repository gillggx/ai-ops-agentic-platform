-- V3 · Add display_name to users (2026-04-25)
--
-- users.username is the login key (local password auth) — immutable.
-- users.email is the OIDC join key — effectively immutable.
-- display_name is the user-facing label — editable via /me/profile.
--
-- Default to username on backfill so existing UI shows something sensible.

ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(150);

UPDATE users SET display_name = username WHERE display_name IS NULL;
