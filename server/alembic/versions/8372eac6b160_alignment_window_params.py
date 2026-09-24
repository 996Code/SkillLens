"""alignment window_params

Revision ID: 8372eac6b160
Revises: 2445db697559
Create Date: 2026-09-24 15:47:35.893915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8372eac6b160'
down_revision: Union[str, Sequence[str], None] = '2445db697559'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 手写（非 autogenerate）：仅加一列，避开 autogenerate 对 raw_event 的假 NOT NULL 噪音（lessons #13）
    op.add_column('alignment',
                  sa.Column('window_params', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('alignment', 'window_params')
