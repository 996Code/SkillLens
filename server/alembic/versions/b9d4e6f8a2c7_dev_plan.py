"""dev_plan 表（S18 T1 夜间开发计划）

- 夜间开发计划行：requirement_text（原始需求）/ target_form（目标表单
  formCode）/ changes（LLM 结构化的字段变更清单 JSON：
  [{op: add_field, field_type, label, key}]）/ status
  draft|confirmed|executed|error / execution_log（T3 执行器逐步动作+
  saveFormConfig 响应摘要，生成阶段 NULL）/ reviewed_by / notes（确定性
  回查失败原因，人工修订依据）/ created_at。
- 生成一律落 draft（C1 延伸：计划不执行，confirm 是独立人工门控）。

Revision ID: b9d4e6f8a2c7
Revises: a8c3e1f7b4d9
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "b9d4e6f8a2c7"
down_revision = "a8c3e1f7b4d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dev_plan",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("requirement_text", sa.Text(), nullable=False),
        sa.Column("target_form", sa.String(100), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="draft"),
        sa.Column("execution_log", sa.JSON(), nullable=True),
        sa.Column("reviewed_by", sa.String(100), nullable=False,
                  server_default=""),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("dev_plan")
