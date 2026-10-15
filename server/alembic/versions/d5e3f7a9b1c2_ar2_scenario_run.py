"""AR2 scenario_run aggregation + replay_run ownership.

Revision ID: d5e3f7a9b1c2
Revises: c4d2e6f8a0b1
Create Date: 2026-10-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d5e3f7a9b1c2"
down_revision = "c4d2e6f8a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_run",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("definition_snapshot", sa.JSON(), nullable=False),
        sa.Column("expectation_snapshot", sa.JSON(), nullable=True),
        sa.Column("trigger", sa.String(20), nullable=False, server_default="api"),
        sa.Column("executor", sa.String(20), nullable=False, server_default="server"),
        sa.Column("mode", sa.String(10), nullable=False, server_default="execute"),
        sa.Column("status", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("source_track", sa.String(20), nullable=False, server_default="demo"),
        sa.Column("confirm_side_effect", sa.Boolean(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), nullable=True),
        sa.Column("pass_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shadow_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_summary", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenario_run_scenario_id", "scenario_run", ["scenario_id"])
    op.create_index("ix_scenario_run_status", "scenario_run", ["status"])

    with op.batch_alter_table("replay_run") as batch:
        batch.add_column(sa.Column("scenario_run_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("execution_index", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False,
                                   server_default="1"))
        batch.add_column(sa.Column("scope_kind", sa.String(20), nullable=False,
                                   server_default="scenario"))
        batch.create_index("ix_replay_run_scenario_run_id", ["scenario_run_id"])
        batch.create_index("ix_replay_run_scenario_run_exec",
                           ["scenario_run_id", "execution_index"])

    # 历史 3115 行无可证明归属 → legacy_unscoped 记账（不猜场景）
    op.execute(sa.text(
        "UPDATE replay_run SET scope_kind = 'legacy_unscoped' "
        "WHERE scenario_run_id IS NULL"))


def downgrade() -> None:
    with op.batch_alter_table("replay_run") as batch:
        batch.drop_index("ix_replay_run_scenario_run_exec")
        batch.drop_index("ix_replay_run_scenario_run_id")
        batch.drop_column("scope_kind")
        batch.drop_column("attempt")
        batch.drop_column("execution_index")
        batch.drop_column("scenario_run_id")
    op.drop_index("ix_scenario_run_status", table_name="scenario_run")
    op.drop_index("ix_scenario_run_scenario_id", table_name="scenario_run")
    op.drop_table("scenario_run")
