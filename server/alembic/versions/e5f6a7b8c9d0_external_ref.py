"""S25 块 W3：expected_delta.external_ref（外部需求条目编号，v1 仅存字段+展示）

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("expected_delta",
                  sa.Column("external_ref", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("expected_delta", "external_ref")
