"""v14: add cumulative_tokens and workspace_state to agent_sessions

Revision ID: 20260307_0005
Revises: (add your previous revision id here if needed)
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = "20260307_0005"
down_revision = None  # set to previous revision id if chaining
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite-compatible: ALTER TABLE ADD COLUMN
    with op.batch_alter_table("agent_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("cumulative_tokens", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("workspace_state", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("agent_sessions") as batch_op:
        batch_op.drop_column("workspace_state")
        batch_op.drop_column("cumulative_tokens")
