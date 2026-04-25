-- V2 · OIDC + role normalization (2026-04-25)
--
-- 1. Normalize users.roles values:
--      it_admin     → IT_ADMIN
--      expert_pe    → PE
--      general_user → ON_DUTY
--    (legacy lowercase from Phase 0-era seed; Java enum is uppercase)
--
-- 2. Add OIDC link columns so we can correlate an external identity back to
--    our users row without creating duplicates. `oidc_provider` + `oidc_sub`
--    together uniquely identify the IdP-side identity. NULL = local-only
--    account.
--
-- 3. New table `role_change_logs` for forensic / audit of role upgrades
--    & demotions performed through /admin/users.

-- ── 1. Normalize roles ───────────────────────────────────────────────────
UPDATE users
SET roles = REPLACE(
              REPLACE(
                REPLACE(roles, 'it_admin', 'IT_ADMIN'),
                'expert_pe', 'PE'),
              'general_user', 'ON_DUTY')
WHERE roles LIKE '%it_admin%'
   OR roles LIKE '%expert_pe%'
   OR roles LIKE '%general_user%';

-- ── 2. OIDC link columns ─────────────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_provider VARCHAR(40);
ALTER TABLE users ADD COLUMN IF NOT EXISTS oidc_sub      VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE;

-- One IdP identity maps to at most one local user row. NULL/NULL pairs (local
-- accounts) are allowed; partial index skips them.
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_oidc_identity
  ON users (oidc_provider, oidc_sub)
  WHERE oidc_provider IS NOT NULL AND oidc_sub IS NOT NULL;

-- ── 3. role_change_logs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS role_change_logs (
  id            BIGSERIAL PRIMARY KEY,
  target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  actor_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  old_roles      TEXT NOT NULL,
  new_roles      TEXT NOT NULL,
  reason         TEXT,
  changed_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_rcl_target ON role_change_logs(target_user_id);
CREATE INDEX IF NOT EXISTS ix_rcl_changed_at ON role_change_logs(changed_at);
