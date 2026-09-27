"""S26：locate_proposal.applied_skill_id（晋升回写生成的新版本 skill）

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locate_proposal",
                  sa.Column("applied_skill_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("locate_proposal", "applied_skill_id")
