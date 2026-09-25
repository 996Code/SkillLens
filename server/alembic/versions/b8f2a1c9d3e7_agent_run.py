"""agent_run（S13 F1：Agent 运行时执行记录——graph 名/输入/节点产物/status/起止/异常）

Revision ID: b8f2a1c9d3e7
Revises: d9b1e4c7a2f5
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "b8f2a1c9d3e7"
down_revision = "d9b1e4c7a2f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("graph_name", sa.String(50), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("node_outputs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_text", sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("agent_run")
