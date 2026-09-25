"""filtered_window

Revision ID: b7e2a4c1f830
Revises: 3f1b7c9a5d02
Create Date: 2026-09-24 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e2a4c1f830'
down_revision: Union[str, Sequence[str], None] = '3f1b7c9a5d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 手写（非 autogenerate，lessons #13）：噪声过滤决策表（S10 Task2，C3 审计）
    op.create_table('filtered_window',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('window_seq', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_filtered_window_session_id'), 'filtered_window',
                    ['session_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_filtered_window_session_id'), table_name='filtered_window')
    op.drop_table('filtered_window')
