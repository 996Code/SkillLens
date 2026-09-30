"""S42-7：field_type_hint 字段类型知识库表（表单校验自愈资产）

Revision ID: b8c9d0e1f2a3
Revises: 6463c9f48646
Create Date: 2026-09-30
"""
from alembic import op
import sqlalchemy as sa

revision = "b8c9d0e1f2a3"
down_revision = "6463c9f48646"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "field_type_hint",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("label_pattern", sa.String(100), nullable=False, index=True),
        sa.Column("field_type", sa.String(30), nullable=False),
        sa.Column("example_value", sa.String(200), nullable=False, server_default=""),
        sa.Column("source", sa.String(20), nullable=False, server_default="learned"),
        sa.Column("source_skill_id", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("field_type_hint")
