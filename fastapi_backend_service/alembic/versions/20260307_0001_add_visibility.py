"""add_visibility_to_mcp_and_skill

Revision ID: add_visibility_001
Revises: 3ece7dfc2a87
Create Date: 2026-03-07 00:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_visibility_001'
down_revision: Union[str, None] = '3ece7dfc2a87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'mcp_definitions',
        sa.Column('visibility', sa.String(10), nullable=False, server_default='private')
    )
    op.add_column(
        'skill_definitions',
        sa.Column('visibility', sa.String(10), nullable=False, server_default='private')
    )


def downgrade() -> None:
    op.drop_column('skill_definitions', 'visibility')
    op.drop_column('mcp_definitions', 'visibility')
