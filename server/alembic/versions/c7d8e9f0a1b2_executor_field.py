"""AG1：replay_run.executor 字段——插件执行端标记（server|extension）。

协议内部态（指令游标/已收证据/介入计数）存 run.plan 的 executor_state 键，
不建表——run 即会话。
"""
revision = "c7d8e9f0a1b2"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column("replay_run",
                  sa.Column("executor", sa.String(20), nullable=False,
                            server_default="server"))


def downgrade() -> None:
    op.drop_column("replay_run", "executor")
