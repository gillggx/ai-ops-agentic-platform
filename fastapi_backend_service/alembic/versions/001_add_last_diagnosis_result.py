"""add last_diagnosis_result to skill_definitions

Revision ID: 001
Revises:
Create Date: 2026-03-03
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_definitions",
        sa.Column("last_diagnosis_result", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("skill_definitions", "last_diagnosis_result")
