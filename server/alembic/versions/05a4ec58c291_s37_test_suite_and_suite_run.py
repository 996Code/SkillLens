"""s37 test_suite and suite_run

Revision ID: 05a4ec58c291
Revises: f6a7b8c9d0e1
Create Date: 2026-09-29 12:12:18.601483

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '05a4ec58c291'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """S37-3 测试套件两表（autogenerate 误检的存量索引/列差异已剔除）。"""
    op.create_table('suite_run',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('suite_id', sa.Integer(), nullable=False),
    sa.Column('results', sa.JSON(), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('pass_count', sa.Integer(), nullable=False),
    sa.Column('fail_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('shadow_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_suite_run_suite_id'), 'suite_run', ['suite_id'], unique=False)
    op.create_table('test_suite',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('skill_ids', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('test_suite')
    op.drop_index(op.f('ix_suite_run_suite_id'), table_name='suite_run')
    op.drop_table('suite_run')
