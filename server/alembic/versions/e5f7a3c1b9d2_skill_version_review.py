"""skill 版本演化（version/superseded_by，S15 I2）+ review 评审表（S15 I1）

- skill.version：Integer，server_default 1（存量行回填 UPDATE ... WHERE version IS NULL）；
- skill.superseded_by：Integer nullable（指向取代它的最新版 skill id，链式指向直接后继）；
- review：夜间 agent_run 的人工评审行（同 run 仅一条，由 API 层 409 保证）。

Revision ID: e5f7a3c1b9d2
Revises: c9e2f4a7b6d1
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "e5f7a3c1b9d2"
down_revision = "c9e2f4a7b6d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill", sa.Column("version", sa.Integer(),
                                     server_default="1", nullable=False))
    op.add_column("skill", sa.Column("superseded_by", sa.Integer(), nullable=True))
    # 存量回填：迁移前创建的 skill 一律视为 v1（v3 §29 不覆盖旧版本）
    op.execute("UPDATE skill SET version = 1 WHERE version IS NULL")
    op.create_table(
        "review",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", sa.Integer(), nullable=False),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # DB 不变量：同 run 仅一条评审（封掉 API 层 409 的并发窗口）
        sa.UniqueConstraint("agent_run_id", name="uq_review_agent_run"),
    )
    op.create_index(op.f("ix_review_agent_run_id"), "review", ["agent_run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_review_agent_run_id"), table_name="review")
    op.drop_table("review")
    op.drop_column("skill", "superseded_by")
    op.drop_column("skill", "version")
