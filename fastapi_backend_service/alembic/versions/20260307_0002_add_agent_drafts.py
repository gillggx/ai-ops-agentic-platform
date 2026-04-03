"""add_agent_drafts_table

Revision ID: add_agent_drafts_002
Revises: add_visibility_001
Create Date: 2026-03-07 00:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_agent_drafts_002'
down_revision: Union[str, None] = 'add_visibility_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_drafts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('draft_type', sa.String(20), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(10), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_agent_drafts_user_id', 'agent_drafts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_agent_drafts_user_id', table_name='agent_drafts')
    op.drop_table('agent_drafts')
