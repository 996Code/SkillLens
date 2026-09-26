"""synth_flow 表（S19 T1 流程生成）

- 生成流程行：goal（用户目标）/ system_hint（系统 API 前缀提示，证据过滤
  依据）/ steps（LLM 目标分解的步骤序列 JSON：
  [{kind: goto|input|click, target, value?}]）/ status
  proposed|executed|failed / notes（确定性回查失败原因或执行自学习提示）/
  evidence_refs（生成时引用的证据快照：skill_ids/anchors/variables/pages/
  api_templates）/ execution_log（T2 执行器逐步结果，生成阶段 NULL）/
  created_at。
- 生成一律落 proposed（回查失败也落库供人工看，notes 记原因）。

Revision ID: d8a3f5c7e9b1
Revises: b9d4e6f8a2c7
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "d8a3f5c7e9b1"
down_revision = "b9d4e6f8a2c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synth_flow",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("system_hint", sa.String(200), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="proposed"),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("execution_log", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("synth_flow")
