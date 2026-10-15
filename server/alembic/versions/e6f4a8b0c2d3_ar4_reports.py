"""AR4 scenario expectations, auto reports, report reviews.

Revision ID: e6f4a8b0c2d3
Revises: d5e3f7a9b1c2
Create Date: 2026-10-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e6f4a8b0c2d3"
down_revision = "d5e3f7a9b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scenario_expectation",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scenario_id", sa.Integer(), nullable=False),
        sa.Column("expected_delta_id", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("confirmed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scenario_expectation_scenario_id",
                    "scenario_expectation", ["scenario_id"])
    op.create_index("ix_scenario_expectation_expected_delta_id",
                    "scenario_expectation", ["expected_delta_id"])
    # SQLite NULL 不参与 UNIQUE：场景级/步骤级分别部分唯一索引
    op.create_index(
        "uq_scexp_scenario_level", "scenario_expectation",
        ["scenario_id", "expected_delta_id"], unique=True,
        sqlite_where=sa.text("step_index IS NULL"))
    op.create_index(
        "uq_scexp_step_level", "scenario_expectation",
        ["scenario_id", "expected_delta_id", "step_index"], unique=True,
        sqlite_where=sa.text("step_index IS NOT NULL"))

    op.create_table(
        "scenario_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scenario_run_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False,
                  server_default="generating"),
        sa.Column("coverage_state", sa.String(20), nullable=False,
                  server_default="no_expectation"),
        sa.Column("source_track", sa.String(20), nullable=False,
                  server_default="demo"),
        sa.Column("expected_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("missing_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("unexpected_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("drift_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_scenario_report_scenario_run_id",
                    "scenario_report", ["scenario_run_id"], unique=True)

    op.create_table(
        "report_delta",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scenario_report_id", sa.Integer(), nullable=False),
        sa.Column("expectation_key", sa.String(64), nullable=False),
        sa.Column("expected_delta_id", sa.Integer(), nullable=False),
        sa.Column("observed_delta_ids", sa.JSON(), nullable=True),
        sa.Column("evidence_replay_run_ids", sa.JSON(), nullable=True),
        sa.Column("expected", sa.JSON(), nullable=True),
        sa.Column("missing", sa.JSON(), nullable=True),
        sa.Column("unexpected", sa.JSON(), nullable=True),
        sa.Column("drift", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scenario_report_id", "expectation_key",
                            name="uq_report_delta_key"),
    )
    op.create_index("ix_report_delta_scenario_report_id",
                    "report_delta", ["scenario_report_id"])

    op.create_table(
        "report_review",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("reviewer", sa.String(100), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_report_review_report_id",
                    "report_review", ["report_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_report_review_report_id", table_name="report_review")
    op.drop_table("report_review")
    op.drop_index("ix_report_delta_scenario_report_id", table_name="report_delta")
    op.drop_table("report_delta")
    op.drop_index("ix_scenario_report_scenario_run_id", table_name="scenario_report")
    op.drop_table("scenario_report")
    op.drop_index("uq_scexp_step_level", table_name="scenario_expectation")
    op.drop_index("uq_scexp_scenario_level", table_name="scenario_expectation")
    op.drop_index("ix_scenario_expectation_expected_delta_id",
                  table_name="scenario_expectation")
    op.drop_index("ix_scenario_expectation_scenario_id",
                  table_name="scenario_expectation")
    op.drop_table("scenario_expectation")
