"""semantic_action state snapshots

Revision ID: c9d41f2a7e03
Revises: 8372eac6b160
Create Date: 2026-09-24 17:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d41f2a7e03'
down_revision: Union[str, Sequence[str], None] = '8372eac6b160'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 手写（非 autogenerate）：仅加两列，避开 autogenerate 对 raw_event 的假 NOT NULL 噪音（lessons #13）
    op.add_column('semantic_action',
                  sa.Column('state_before', sa.JSON(), nullable=True))
    op.add_column('semantic_action',
                  sa.Column('state_after', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('semantic_action', 'state_after')
    op.drop_column('semantic_action', 'state_before')
