"""fix data_subject_id nullable — SQLite table rebuild

Revision ID: fix_ds_nullable_005
Revises: add_v13_agent_004
Create Date: 2026-03-07 00:05:00.000000

SQLite cannot ALTER COLUMN to drop NOT NULL, so we rebuild the table.
This makes data_subject_id nullable so system MCPs (mcp_type='system')
can be inserted without a data_subject_id FK.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'fix_ds_nullable_005'
down_revision: Union[str, None] = 'add_v13_agent_004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Check pragma: notnull=1 means NOT NULL constraint is active
    row = conn.execute(sa.text(
        "SELECT [notnull] FROM pragma_table_info('mcp_definitions') "
        "WHERE name='data_subject_id'"
    )).fetchone()

    if row is None or row[0] == 0:
        # Column is already nullable (or missing) — nothing to do
        return

    # ── SQLite table rebuild to drop NOT NULL from data_subject_id ────────────
    op.execute("""
        CREATE TABLE mcp_definitions_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            name              VARCHAR(200) NOT NULL UNIQUE,
            description       TEXT        NOT NULL DEFAULT '',
            mcp_type          VARCHAR(10) NOT NULL DEFAULT 'custom',
            api_config        TEXT,
            input_schema      TEXT,
            system_mcp_id     INTEGER REFERENCES mcp_definitions_new(id) ON DELETE RESTRICT,
            data_subject_id   INTEGER REFERENCES data_subjects(id) ON DELETE RESTRICT,
            processing_intent TEXT        NOT NULL DEFAULT '',
            processing_script TEXT,
            output_schema     TEXT,
            ui_render_config  TEXT,
            input_definition  TEXT,
            sample_output     TEXT,
            visibility        VARCHAR(10) NOT NULL DEFAULT 'private',
            created_at        DATETIME    NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at        DATETIME    NOT NULL DEFAULT (CURRENT_TIMESTAMP)
        )
    """)

    op.execute("""
        INSERT INTO mcp_definitions_new
            (id, name, description, mcp_type, api_config, input_schema,
             system_mcp_id, data_subject_id, processing_intent, processing_script,
             output_schema, ui_render_config, input_definition, sample_output,
             visibility, created_at, updated_at)
        SELECT
            id, name, description,
            COALESCE(mcp_type, 'custom'),
            api_config, input_schema, system_mcp_id, data_subject_id,
            COALESCE(processing_intent, ''), processing_script,
            output_schema, ui_render_config, input_definition, sample_output,
            COALESCE(visibility, 'private'), created_at, updated_at
        FROM mcp_definitions
    """)

    op.execute("DROP TABLE mcp_definitions")
    op.execute("ALTER TABLE mcp_definitions_new RENAME TO mcp_definitions")


def downgrade() -> None:
    pass
