-- 真 Skill 化 (2026-07-08): skill 說明書（人審後的 use_case/when_to_use/tags JSON）
ALTER TABLE skills_v2 ADD COLUMN IF NOT EXISTS doc TEXT;
