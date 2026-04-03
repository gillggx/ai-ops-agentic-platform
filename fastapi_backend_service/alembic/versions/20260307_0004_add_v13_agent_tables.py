"""add_v13_agent_tables

Revision ID: add_v13_agent_004
Revises: add_system_mcp_003
Create Date: 2026-03-07 12:00:00.000000

Creates three tables for the v13 Real Agentic Platform:
  - agent_memories    (long-term RAG memory)
  - user_preferences  (per-user AI preferences)
  - agent_sessions    (short-term conversation cache)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'add_v13_agent_004'
down_revision: Union[str, None] = 'add_system_mcp_003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_memories',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('embedding', sa.Text(), nullable=True),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('ref_id', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_agent_memories_user_id', 'agent_memories', ['user_id'])

    op.create_table(
        'user_preferences',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('preferences', sa.Text(), nullable=True),
        sa.Column('soul_override', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_user_preferences_user_id', 'user_preferences', ['user_id'])

    op.create_table(
        'agent_sessions',
        sa.Column('session_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('messages', sa.Text(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_agent_sessions_user_id', 'agent_sessions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_agent_sessions_user_id', table_name='agent_sessions')
    op.drop_table('agent_sessions')
    op.drop_index('ix_user_preferences_user_id', table_name='user_preferences')
    op.drop_table('user_preferences')
    op.drop_index('ix_agent_memories_user_id', table_name='agent_memories')
    op.drop_table('agent_memories')
