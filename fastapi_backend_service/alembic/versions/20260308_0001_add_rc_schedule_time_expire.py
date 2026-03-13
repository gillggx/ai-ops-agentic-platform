"""Add expire_at and schedule_time to routine_checks.

Revision ID: rc_schedule_time_006
Revises: fix_ds_nullable_005
Create Date: 2026-03-08
"""
from typing import Union

from alembic import op

revision: str = 'rc_schedule_time_006'
down_revision: Union[str, None] = '20260307_0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE routine_checks ADD COLUMN expire_at TEXT")
    op.execute("ALTER TABLE routine_checks ADD COLUMN schedule_time VARCHAR(5)")


def downgrade() -> None:
    pass
