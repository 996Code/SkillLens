"""S22 块 T：visual_baseline 表（视觉回归基线）

- skill_id 唯一（每 skill 一条基线）；file_path 指向 artifacts/visual/{sid}/baseline.png；
- image_hash 为 16 位十六进制 dHash（供快速比对与审计）；
- source_run_id 指向建基线的那次 execute PASS 回放。

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_baseline",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(300), nullable=False),
        sa.Column("image_hash", sa.String(16), nullable=False, server_default=""),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_run_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id"),
    )
    op.create_index(op.f("ix_visual_baseline_skill_id"), "visual_baseline", ["skill_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_visual_baseline_skill_id"), table_name="visual_baseline")
    op.drop_table("visual_baseline")
