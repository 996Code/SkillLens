"""replay_run failure_class

Revision ID: 38909f456d13
Revises: 7d37f2e57c2e
Create Date: 2026-10-08 23:22:38.253565

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision: str = '38909f456d13'
down_revision: Union[str, Sequence[str], None] = '7d37f2e57c2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('replay_run',
                  sa.Column('failure_class', sa.String(20), nullable=True))
    op.create_index(op.f('ix_replay_run_failure_class'), 'replay_run',
                    ['failure_class'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_replay_run_failure_class'), table_name='replay_run')
    op.drop_column('replay_run', 'failure_class')
