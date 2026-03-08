"""Add mock_data_sources table for Mock Data Studio.

Revision ID: mock_data_studio_007
Revises: rc_schedule_time_006
Create Date: 2026-03-08
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = 'mock_data_studio_007'
down_revision: Union[str, None] = 'rc_schedule_time_006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'mock_data_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('input_schema', sa.Text(), nullable=True),
        sa.Column('python_code', sa.Text(), nullable=True),
        sa.Column('sample_output', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_mock_data_sources_name', 'mock_data_sources', ['name'])


def downgrade() -> None:
    op.drop_index('ix_mock_data_sources_name', 'mock_data_sources')
    op.drop_table('mock_data_sources')
