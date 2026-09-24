"""skill_strategy 表（Sprint 10 T3：多路径分桶落地 spec §5 定义）

Revision ID: d1c4f6a8b920
Revises: b7e2a4c1f830
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "d1c4f6a8b920"
down_revision = "b7e2a4c1f830"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_strategy",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("strategy_signature", sa.Text(), nullable=False),
        sa.Column("skeleton", sa.JSON()),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_skill_strategy_skill_id", "skill_strategy", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_skill_strategy_skill_id", table_name="skill_strategy")
    op.drop_table("skill_strategy")
