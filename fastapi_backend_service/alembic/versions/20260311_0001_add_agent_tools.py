"""Add agent_tools table (v15.0 JIT Analyst)

Revision ID: add_agent_tools_v150
Revises: add_memory_metadata_v141
Create Date: 2026-03-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "add_agent_tools_v150"
down_revision: str = "add_memory_metadata_v141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_tools",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agent_tools_user_id", "agent_tools", ["user_id"])
    op.create_index("ix_agent_tools_name", "agent_tools", ["name"])


def downgrade() -> None:
    op.drop_index("ix_agent_tools_name", table_name="agent_tools")
    op.drop_index("ix_agent_tools_user_id", table_name="agent_tools")
    op.drop_table("agent_tools")
