-- V13 · Widen role_change_logs.{target,actor}_user_id INTEGER → BIGINT (2026-05-02)
--
-- V2__oidc_user_extras.sql declared these as INTEGER but users.id is BIGINT
-- (SERIAL→BIGINT in the baseline JPA-generated schema). Cosmetic alignment so
-- the JPA entity can use Long like every other FK in the codebase. No data
-- loss — INTEGER values fit BIGINT.
--
-- Per CLAUDE.md note: prod runs Flyway disabled, so this migration only takes
-- effect on a fresh schema; existing prod requires a manual ALTER + bump of
-- flyway_schema_history (insert row with installed_rank > 12).

ALTER TABLE role_change_logs
	ALTER COLUMN target_user_id TYPE BIGINT,
	ALTER COLUMN actor_user_id  TYPE BIGINT;
