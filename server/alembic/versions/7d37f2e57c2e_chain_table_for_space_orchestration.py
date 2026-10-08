"""chain table for space orchestration

Revision ID: 7d37f2e57c2e
Revises: a3f1c8d2e6b4
Create Date: 2026-10-08 12:16:29.875451

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '7d37f2e57c2e'
down_revision: Union[str, Sequence[str], None] = 'a3f1c8d2e6b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """AH1：chain 表（链=纯数据：name/system/steps JSON）。
    autogenerate 附带的历史 alter 噪声已剔除——列/索引集合由
    tests/test_schema_drift.py 守卫，这里只做本块新增。"""
    op.create_table('chain',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('system', sa.String(length=40), nullable=False),
    sa.Column('steps', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chain_system'), 'chain', ['system'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_chain_system'), table_name='chain')
    op.drop_table('chain')
