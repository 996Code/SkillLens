"""field_change

Revision ID: 0a339dc2a198
Revises: 623e1fd553b8
Create Date: 2026-09-23 19:18:19.906775

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a339dc2a198'
down_revision: Union[str, Sequence[str], None] = '623e1fd553b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('field_change',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('api_template', sa.String(length=500), nullable=False),
    sa.Column('before_seq', sa.Integer(), nullable=False),
    sa.Column('after_seq', sa.Integer(), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_field_change_session_id'), 'field_change', ['session_id'], unique=False)
    # 注：autogenerate 另检测到的 raw_event 列 nullable 差异为 SQLite 误报（模型未变），已剔除。


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_field_change_session_id'), table_name='field_change')
    op.drop_table('field_change')
