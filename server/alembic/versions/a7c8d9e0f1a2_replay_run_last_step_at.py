"""replay_run.last_step_at 落列+收割索引

Revision ID: a7c8d9e0f1a2
Revises: f6a7b8c9d0e1
Create Date: 2026-10-10

健壮性体检🟡：收割判据原在 plan JSON（整行反序列化 MB 级）——
列化后 (executor,status,last_step_at) 直查。数据回填：从既有 running
行的 executor_state.last_step_at 迁移（无则空=回退 created_at 语义）。
"""
import sqlalchemy as sa
from alembic import op

revision = "a7c8d9e0f1a2"
down_revision = "38909f456d13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("replay_run",
                  sa.Column("last_step_at", sa.DateTime(), nullable=True))
    op.create_index("ix_replay_run_reap",
                    "replay_run", ["executor", "status", "last_step_at"])
    # 回填：running 行的 plan.executor_state.last_step_at → 列
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, plan FROM replay_run "
        "WHERE status='running' AND executor='extension'")).fetchall()
    import json as _json
    for rid, plan in rows:
        try:
            st = (_json.loads(plan) if isinstance(plan, str) else plan or {}) \
                .get("executor_state") or {}
            ts = st.get("last_step_at")
            if ts:
                conn.execute(sa.text(
                    "UPDATE replay_run SET last_step_at=:t WHERE id=:i"),
                    {"t": ts.replace("T", " ").split(".")[0][:19], "i": rid})
        except Exception:
            continue


def downgrade() -> None:
    op.drop_index("ix_replay_run_reap", table_name="replay_run")
    op.drop_column("replay_run", "last_step_at")
