"""S24 块 U：replay_run.flaky + locate_proposal 表（自愈与维护闭环）

- flaky：首试 fail 重试 pass 的回放标记（两次结果不一致），进一致性统计；
- locate_proposal：定位修复提案库——LLM 提案 + 确定性验证（locate 实测），
  verified/promoted 参与回放自愈，rejected 人工否决。

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("replay_run", sa.Column("flaky", sa.Boolean(),
                                         nullable=False, server_default=sa.false()))
    op.create_table(
        "locate_proposal",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("skill_id", sa.Integer(), nullable=False),
        sa.Column("step_label", sa.String(200), nullable=False),
        sa.Column("proposed_label", sa.String(200), nullable=False),
        sa.Column("strategy", sa.String(30), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("verify_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_locate_proposal_skill_id"), "locate_proposal", ["skill_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_locate_proposal_skill_id"), table_name="locate_proposal")
    op.drop_table("locate_proposal")
    op.drop_column("replay_run", "flaky")
