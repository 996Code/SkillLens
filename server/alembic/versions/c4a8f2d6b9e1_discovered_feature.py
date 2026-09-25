"""discovered_feature 表（Sprint 12 N1：新功能增量发现）

Revision ID: c4a8f2d6b9e1
Revises: f3e6b8d0a214
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "c4a8f2d6b9e1"
down_revision = "f3e6b8d0a214"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovered_feature",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("session_id", sa.String(36), nullable=False),
        # 纯 UI 发现行 api_template 为空（锚点 label 发现）
        sa.Column("api_template", sa.String(300), nullable=True),
        sa.Column("anchor_label", sa.String(200), nullable=True),
        sa.Column("observed_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(), server_default=sa.func.now()),
        # new | linked | dismissed（N2 confirm 对齐后 → linked）
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column("linked_delta_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_discovered_feature_session_id", "discovered_feature", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_discovered_feature_session_id", table_name="discovered_feature")
    op.drop_table("discovered_feature")
