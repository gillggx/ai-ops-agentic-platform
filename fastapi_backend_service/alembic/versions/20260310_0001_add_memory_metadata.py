"""Add metadata columns to agent_memories (v14.1 Hybrid Memory)

Revision ID: add_memory_metadata_v141
Revises: mock_data_studio_007
Create Date: 2026-03-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "add_memory_metadata_v141"
down_revision: str = "mock_data_studio_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("agent_memories", schema=None) as batch_op:
        batch_op.add_column(sa.Column("task_type", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("data_subject", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("tool_name", sa.String(100), nullable=True))

    op.create_index("ix_agent_memories_task_type", "agent_memories", ["task_type"])
    op.create_index("ix_agent_memories_data_subject", "agent_memories", ["data_subject"])


def downgrade() -> None:
    op.drop_index("ix_agent_memories_data_subject", table_name="agent_memories")
    op.drop_index("ix_agent_memories_task_type", table_name="agent_memories")
    with op.batch_alter_table("agent_memories", schema=None) as batch_op:
        batch_op.drop_column("tool_name")
        batch_op.drop_column("data_subject")
        batch_op.drop_column("task_type")
