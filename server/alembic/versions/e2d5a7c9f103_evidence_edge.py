"""evidence_edge 表（Sprint 10 T4：spec §5 证据图基础边）

Revision ID: e2d5a7c9f103
Revises: d1c4f6a8b920
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "e2d5a7c9f103"
down_revision = "d1c4f6a8b920"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_edge",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("src", sa.String(300), nullable=False),
        sa.Column("dst", sa.String(300), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("src", "dst", "type", name="uq_evidence_edge"),
    )
    op.create_index("ix_evidence_edge_src", "evidence_edge", ["src"])
    op.create_index("ix_evidence_edge_dst", "evidence_edge", ["dst"])


def downgrade() -> None:
    op.drop_index("ix_evidence_edge_dst", table_name="evidence_edge")
    op.drop_index("ix_evidence_edge_src", table_name="evidence_edge")
    op.drop_table("evidence_edge")
