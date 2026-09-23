"""skill

Revision ID: 59cf81e18181
Revises: 0a339dc2a198
Create Date: 2026-09-23 19:19:49.653958

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59cf81e18181'
down_revision: Union[str, Sequence[str], None] = '0a339dc2a198'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('skill',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('alignment_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('skeleton', sa.JSON(), nullable=False),
    sa.Column('param_variables', sa.JSON(), nullable=False),
    sa.Column('input_variables', sa.JSON(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('evidence_count', sa.Integer(), nullable=False),
    sa.Column('notes', sa.String(length=500), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_skill_alignment_id'), 'skill', ['alignment_id'], unique=False)
    # 注：autogenerate 另检测到的 raw_event 列 nullable 差异为 SQLite 误报（模型未变），已剔除。


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_skill_alignment_id'), table_name='skill')
    op.drop_table('skill')
