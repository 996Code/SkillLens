"""replay_run.created_at 排序索引——UI 性能批（2026-10-14 体检）

timeline/dashboard/trends 的 ORDER BY created_at DESC LIMIT N 全表扫描
拖着 plan 列溢出页链（均值 1.3MB/行，实测 50 行取回 1.8s、整行版
34.7s）。索引后索引序取行零扫描。

Revision ID: b3c1d5e7f9a2
Revises: a7c8d9e0f1a2
"""
import sqlalchemy as sa
from alembic import op

revision = "b3c1d5e7f9a2"
down_revision = "a7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_replay_run_created_at",
                    "replay_run", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_replay_run_created_at", table_name="replay_run")
