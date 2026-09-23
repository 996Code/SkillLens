"""llm_call_log

Revision ID: 623e1fd553b8
Revises: 044494e885c6
Create Date: 2026-09-23 19:13:30.199030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '623e1fd553b8'
down_revision: Union[str, Sequence[str], None] = '044494e885c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 注：autogenerate 同时检测到的 raw_event 三个 NOT NULL 为既有库与模型比对噪音，非本次变更，已裁剪
    op.create_table('llm_call_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('purpose', sa.String(length=50), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('response', sa.Text(), nullable=False),
    sa.Column('prompt_tokens', sa.Integer(), nullable=True),
    sa.Column('completion_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('llm_call_log')
