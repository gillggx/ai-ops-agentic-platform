"""add feedback_logs table

Revision ID: 20260312_0001
Revises: 20260311_0001
Create Date: 2026-03-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260312_0001"
down_revision = "20260311_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_logs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("target_type", sa.String(10), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("user_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("previous_result_summary", sa.Text(), nullable=True),
        sa.Column("llm_reflection", sa.Text(), nullable=True),
        sa.Column("revised_script", sa.Text(), nullable=True),
        sa.Column("rerun_success", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_feedback_logs_target_type", "feedback_logs", ["target_type"])
    op.create_index("ix_feedback_logs_target_id", "feedback_logs", ["target_id"])


def downgrade() -> None:
    op.drop_table("feedback_logs")
