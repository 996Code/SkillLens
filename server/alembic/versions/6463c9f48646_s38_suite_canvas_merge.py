"""s38 suite canvas merge

Revision ID: 6463c9f48646
Revises: 05a4ec58c291
Create Date: 2026-09-29 13:05:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '6463c9f48646'
down_revision: Union[str, Sequence[str], None] = '05a4ec58c291'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """S38 套件↔流水线合并（autogenerate 误检的存量索引差异已剔除）。"""
    op.add_column('suite_run', sa.Column('agent_run_id', sa.Integer(), nullable=True))
    op.add_column('test_suite', sa.Column('canvas_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('test_suite', 'canvas_id')
    op.drop_column('suite_run', 'agent_run_id')
