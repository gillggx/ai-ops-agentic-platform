"""add_system_mcp_columns — 萬物皆 MCP Phase 1

Revision ID: add_system_mcp_003
Revises: add_agent_drafts_002
Create Date: 2026-03-07 00:03:00.000000

Adds mcp_type / api_config / input_schema / system_mcp_id to mcp_definitions,
then migrates all existing DataSubjects as system MCPs and wires custom MCPs to them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_system_mcp_003'
down_revision: Union[str, None] = 'add_agent_drafts_002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Schema: add new columns ────────────────────────────────────────────
    op.add_column('mcp_definitions',
        sa.Column('mcp_type', sa.String(10), nullable=False, server_default='custom'))
    op.add_column('mcp_definitions',
        sa.Column('api_config', sa.Text(), nullable=True))
    op.add_column('mcp_definitions',
        sa.Column('input_schema', sa.Text(), nullable=True))
    op.add_column('mcp_definitions',
        sa.Column('system_mcp_id', sa.Integer(), nullable=True))

    # ── 2. Data: copy DataSubjects → system MCPs ──────────────────────────────
    # Skip rows where a system MCP with that name already exists (idempotent).
    op.execute("""
        INSERT INTO mcp_definitions
            (name, description, mcp_type, api_config, input_schema,
             processing_intent, visibility, created_at, updated_at)
        SELECT
            name, description, 'system', api_config, input_schema,
            '', 'public', created_at, updated_at
        FROM data_subjects
        WHERE name NOT IN (
            SELECT name FROM mcp_definitions WHERE mcp_type = 'system'
        )
    """)

    # ── 3. Data: wire custom MCPs → their system MCP counterpart ─────────────
    op.execute("""
        UPDATE mcp_definitions
        SET system_mcp_id = (
            SELECT sys.id
            FROM mcp_definitions sys
            JOIN data_subjects ds ON sys.name = ds.name
            WHERE sys.mcp_type = 'system'
              AND ds.id = mcp_definitions.data_subject_id
        )
        WHERE mcp_type = 'custom'
          AND data_subject_id IS NOT NULL
          AND system_mcp_id IS NULL
    """)


def downgrade() -> None:
    # Remove the system MCP rows we inserted (identified by mcp_type='system')
    op.execute("DELETE FROM mcp_definitions WHERE mcp_type = 'system'")
    op.drop_column('mcp_definitions', 'system_mcp_id')
    op.drop_column('mcp_definitions', 'input_schema')
    op.drop_column('mcp_definitions', 'api_config')
    op.drop_column('mcp_definitions', 'mcp_type')
