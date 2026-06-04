-- V54 — MCP form 擴充：System MCP 可選擇連動產生 data block + published skill。
--
-- Background (2026-06-03):
-- 新增一個 System MCP 後，要讓 Pipeline Builder 能用到，過去必須手動建
-- pb_blocks row + 寫 Flyway 註冊 pb_published_skills。三邊 description 容易飄移
-- 違反 CLAUDE.md「MCP description = single source of truth」原則。
--
-- 本 migration 新增 schema 支援：
--   1. mcp_definitions: produces_block / produces_skill / block_generation_meta
--   2. pb_blocks: source + source_mcp_id (區分 manual vs mcp_auto)
--   3. pb_published_skills: source + source_mcp_id
--   4. mcp_generation_drafts: LLM 草稿暫存區（user 確認前不入正式表）
--
-- Flyway disabled in prod — apply on EC2:
--   psql -h localhost -U aiops aiops_db -f V54__mcp_produces_block_and_skill.sql

-- ─── 1. mcp_definitions 擴充 ──────────────────────────────────────────────

ALTER TABLE mcp_definitions
  ADD COLUMN IF NOT EXISTS produces_block         BOOLEAN     NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS produces_skill         BOOLEAN     NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS block_generation_meta  TEXT;

COMMENT ON COLUMN mcp_definitions.produces_block IS
  'true = 此 MCP 在 Pipeline Builder 有一個自動生成的 data block (source=mcp_auto)';
COMMENT ON COLUMN mcp_definitions.produces_skill IS
  'true = 此 MCP 同時生成一個 1-block pipeline + published skill';
COMMENT ON COLUMN mcp_definitions.block_generation_meta IS
  'JSON: {llm_model, prompt_version, generated_at, last_regenerated_at} for audit';

-- ─── 2. pb_blocks 加 source 標記 ──────────────────────────────────────────

ALTER TABLE pb_blocks
  ADD COLUMN IF NOT EXISTS source         TEXT NOT NULL DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS source_mcp_id  BIGINT;

-- 既有 27 個 hand-crafted block 預設為 manual（DEFAULT 已涵蓋）

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pb_blocks_source_chk') THEN
    ALTER TABLE pb_blocks ADD CONSTRAINT pb_blocks_source_chk
      CHECK (source IN ('manual', 'mcp_auto'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pb_blocks_source_mcp_fk') THEN
    ALTER TABLE pb_blocks ADD CONSTRAINT pb_blocks_source_mcp_fk
      FOREIGN KEY (source_mcp_id) REFERENCES mcp_definitions(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_pb_blocks_source_mcp_id ON pb_blocks(source_mcp_id);

COMMENT ON COLUMN pb_blocks.source IS
  'manual = hand-crafted / seeded; mcp_auto = LLM-generated from a System MCP description';
COMMENT ON COLUMN pb_blocks.source_mcp_id IS
  'FK to mcp_definitions when source=mcp_auto. NULL when manual. SET NULL on MCP delete (block detached but kept).';

-- ─── 3. pb_published_skills 加 source 標記 ────────────────────────────────

ALTER TABLE pb_published_skills
  ADD COLUMN IF NOT EXISTS source         TEXT NOT NULL DEFAULT 'manual',
  ADD COLUMN IF NOT EXISTS source_mcp_id  BIGINT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pb_published_skills_source_chk') THEN
    ALTER TABLE pb_published_skills ADD CONSTRAINT pb_published_skills_source_chk
      CHECK (source IN ('manual', 'mcp_auto'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pb_published_skills_source_mcp_fk') THEN
    ALTER TABLE pb_published_skills ADD CONSTRAINT pb_published_skills_source_mcp_fk
      FOREIGN KEY (source_mcp_id) REFERENCES mcp_definitions(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_pb_published_skills_source_mcp_id ON pb_published_skills(source_mcp_id);

-- ─── 4. mcp_generation_drafts (LLM 草稿暫存) ──────────────────────────────

CREATE TABLE IF NOT EXISTS mcp_generation_drafts (
  id              BIGSERIAL PRIMARY KEY,
  mcp_draft       TEXT NOT NULL,                                              -- JSON: 表單目前狀態（MCP 欄位）
  block_draft     TEXT,                                                       -- JSON: LLM 生成的 block 草稿
  skill_draft     TEXT,                                                       -- JSON: LLM 生成的 skill 草稿
  lint_issues     TEXT NOT NULL DEFAULT '[]',                                 -- JSON list
  llm_model       TEXT,
  prompt_version  TEXT,
  input_tokens    INTEGER NOT NULL DEFAULT 0,
  output_tokens   INTEGER NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','committed','discarded')),
  created_by      BIGINT,                                                     -- user id (mirrors mcp_definitions auth pattern)
  created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
  committed_mcp_id BIGINT REFERENCES mcp_definitions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS ix_mcp_generation_drafts_status_created
  ON mcp_generation_drafts(status, created_at DESC);

COMMENT ON TABLE mcp_generation_drafts IS
  'LLM 為 MCP 生成 block + skill 草稿的暫存區。User 在 form 內確認後 status→committed 並建立 pb_blocks/pb_published_skills rows。';
