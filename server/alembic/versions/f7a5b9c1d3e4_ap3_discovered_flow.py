"""AP3 discovered_flow table.

Revision ID: f7a5b9c1d3e4
Revises: e6f4a8b0c2d3
Create Date: 2026-10-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f7a5b9c1d3e4"
down_revision = "e6f4a8b0c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovered_flow",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="pending"),
        sa.Column("discard_reason", sa.String(100), nullable=False,
                  server_default=""),
        sa.Column("has_write", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("skill_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_discovered_flow_session_id",
                    "discovered_flow", ["session_id"])
    op.create_index("ix_discovered_flow_status",
                    "discovered_flow", ["status"])


def downgrade() -> None:
    op.drop_index("ix_discovered_flow_status", table_name="discovered_flow")
    op.drop_index("ix_discovered_flow_session_id", table_name="discovered_flow")
    op.drop_table("discovered_flow")
