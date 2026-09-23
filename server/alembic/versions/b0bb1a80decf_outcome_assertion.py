"""outcome_assertion

Revision ID: b0bb1a80decf
Revises: 59cf81e18181
Create Date: 2026-09-23 19:26:47.764869

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b0bb1a80decf'
down_revision: Union[str, Sequence[str], None] = '59cf81e18181'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('outcome_assertion',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('skill_id', sa.Integer(), nullable=False),
    sa.Column('layer', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('api_template', sa.String(length=500), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_outcome_assertion_skill_id'), 'outcome_assertion', ['skill_id'], unique=False)
    # 注：autogenerate 另检测到的 raw_event 列 nullable 差异为 SQLite 误报（模型未变），已剔除。


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_outcome_assertion_skill_id'), table_name='outcome_assertion')
    op.drop_table('outcome_assertion')
