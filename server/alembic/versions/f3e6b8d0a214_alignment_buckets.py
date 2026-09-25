"""alignment.buckets 列（Sprint 10 T3：分桶骨架持久化供 induce 使用）

Revision ID: f3e6b8d0a214
Revises: e2d5a7c9f103
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "f3e6b8d0a214"
down_revision = "e2d5a7c9f103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alignment", sa.Column("buckets", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("alignment", "buckets")
