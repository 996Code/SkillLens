"""recording_session source

Revision ID: 3f1b7c9a5d02
Revises: c9d41f2a7e03
Create Date: 2026-09-24 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f1b7c9a5d02'
down_revision: Union[str, Sequence[str], None] = 'c9d41f2a7e03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 手写（非 autogenerate）：单列新增，server_default 兜底存量行为 demo（lessons #13）
    op.add_column('recording_session',
                  sa.Column('source', sa.String(length=20), nullable=False,
                            server_default='demo'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recording_session', 'source')
