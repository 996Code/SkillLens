"""outcome_assertion.evidence_count（S12 N4 层4：verify 通过次数累加）

Revision ID: d9b1e4c7a2f5
Revises: c4a8f2d6b9e1
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "d9b1e4c7a2f5"
down_revision = "c4a8f2d6b9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outcome_assertion",
                  sa.Column("evidence_count", sa.Integer(), nullable=False,
                            server_default="0"))


def downgrade() -> None:
    op.drop_column("outcome_assertion", "evidence_count")
