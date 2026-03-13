"""fix data_subject_id nullable

Revision ID: fix_ds_nullable_005
Revises: add_v13_agent_004
Create Date: 2026-03-07 00:05:00.000000

Make data_subject_id nullable so system MCPs (mcp_type='system')
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

    # Check if column is already nullable via information_schema (PostgreSQL + SQLite compatible)
    row = conn.execute(sa.text(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name='mcp_definitions' AND column_name='data_subject_id'"
    )).fetchone()

    if row is None or row[0] == 'YES':
        # Column missing or already nullable — nothing to do
        return

    # PostgreSQL: simple ALTER COLUMN DROP NOT NULL
    op.alter_column('mcp_definitions', 'data_subject_id', nullable=True)


def downgrade() -> None:
    pass
