-- V81: per-user UI theme preference (design handoff v2 — 10 selectable themes).
-- Mirrors the `locale` preference pattern. NULL = platform default (pine).
ALTER TABLE users ADD COLUMN IF NOT EXISTS ui_theme VARCHAR(24);

COMMENT ON COLUMN users.ui_theme IS
  'UI theme slug (oxblood/aubergine/petrol/olive/slate/raspberry/lime/cocoa/'
  'violet/pine). NULL = default (pine). User preference, set from the account menu.';
