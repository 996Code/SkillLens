"""alignment

Revision ID: 044494e885c6
Revises: 2de33db18300
Create Date: 2026-09-23 17:59:17.610956

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '044494e885c6'
down_revision: Union[str, Sequence[str], None] = '2de33db18300'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('alignment',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_ids', sa.JSON(), nullable=False),
    sa.Column('skeleton', sa.JSON(), nullable=False),
    sa.Column('param_variables', sa.JSON(), nullable=False),
    sa.Column('input_variables', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alignment')
