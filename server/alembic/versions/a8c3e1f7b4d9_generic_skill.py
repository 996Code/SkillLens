"""generic_skill 表（S17 块 L 通用能力层）

- 通用能力资产行：name/description/slots_schema（槽位定义 JSON）/
  status candidate|learned / source_skill_ids（源 skill 引用 JSON）/
  evidence_refs（证据引用 JSON：骨架步数/变量名）/notes/created_at。
- 归纳（induce）只落 candidate；晋升（promote）是独立确定性步骤 → learned。

Revision ID: a8c3e1f7b4d9
Revises: e5f7a3c1b9d2
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa

revision = "a8c3e1f7b4d9"
down_revision = "e5f7a3c1b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generic_skill",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("slots_schema", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="candidate"),
        sa.Column("source_skill_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("generic_skill")
