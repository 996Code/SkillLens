"""canvas_dag（S14 H2：编排画布 DAG——版本化保存，每次保存新行不覆盖）

Revision ID: c9e2f4a7b6d1
Revises: b8f2a1c9d3e7
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa

revision = "c9e2f4a7b6d1"
down_revision = "b8f2a1c9d3e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canvas_dag",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("dag", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("canvas_dag")
