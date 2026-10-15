"""AR1 converge chain identity into scenario.

Revision ID: c4d2e6f8a0b1
Revises: b3c1d5e7f9a2
Create Date: 2026-10-15
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session

revision = "c4d2e6f8a0b1"
down_revision = "b3c1d5e7f9a2"
branch_labels = None
depends_on = None


def _loads(value):
    if isinstance(value, str):
        return json.loads(value)
    return value or []


def _rewrite_step_key(table: str, old_key: str, new_key: str) -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, steps FROM {table}")).fetchall()
    for row_id, raw_steps in rows:
        steps = _loads(raw_steps)
        changed = False
        for step in steps:
            if old_key in step:
                step[new_key] = step.pop(old_key)
                changed = True
        if changed:
            bind.execute(
                sa.text(f"UPDATE {table} SET steps = :steps WHERE id = :id"),
                {"steps": json.dumps(steps, ensure_ascii=False), "id": row_id},
            )


def _migrate_suites() -> None:
    from app.models import Scenario, TestSuite
    from app.scenario.migration import classify_suite_definition
    from app.system import skill_systems

    bind = op.get_bind()
    db = Session(bind=bind)
    scenarios = [
        {"id": row.id, "system": row.system, "steps": row.steps or []}
        for row in db.query(Scenario).all()
    ]
    for suite in db.query(TestSuite).all():
        ids = [int(value) for value in (suite.skill_ids or [])]
        decision = classify_suite_definition(
            suite_skill_ids=ids,
            skill_systems=skill_systems(db, ids),
            scenarios=scenarios,
        )
        if decision.kind == "reuse":
            suite.scenario_id = decision.scenario_id
            suite.migration_status = "reused"
        elif decision.kind == "create":
            scenario = Scenario(
                name=suite.name,
                system=decision.system or "未知系统",
                steps=[{"skill_id": skill_id, "scenario_id": None,
                        "overrides": {}, "setup": False, "enabled": True}
                       for skill_id in ids],
                status="active",
                definition_version=1,
                origin="legacy_suite",
                created_at=suite.created_at,
                updated_at=suite.created_at,
            )
            db.add(scenario)
            db.flush()
            suite.scenario_id = scenario.id
            suite.migration_status = "created"
            scenarios.append({"id": scenario.id, "system": scenario.system,
                              "steps": scenario.steps})
        else:
            suite.migration_status = decision.kind
        suite.migration_reason = decision.reason
    db.flush()


def upgrade() -> None:
    op.rename_table("chain", "scenario")
    try:
        op.drop_index("ix_chain_system", table_name="scenario")
    except Exception:
        pass

    with op.batch_alter_table("scenario") as batch:
        batch.add_column(sa.Column("status", sa.String(20), nullable=False,
                                   server_default="active"))
        batch.add_column(sa.Column("definition_version", sa.Integer(), nullable=False,
                                   server_default="1"))
        batch.add_column(sa.Column("origin", sa.String(30), nullable=False,
                                   server_default="manual"))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_index("ix_scenario_system", ["system"])
        batch.create_index("ix_scenario_status", ["status"])
    op.execute(sa.text("UPDATE scenario SET updated_at = created_at WHERE updated_at IS NULL"))
    with op.batch_alter_table("scenario") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True),
                           nullable=False)

    _rewrite_step_key("scenario", "chain_id", "scenario_id")

    with op.batch_alter_table("test_suite") as batch:
        batch.add_column(sa.Column("scenario_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("migration_status", sa.String(30), nullable=False,
                                   server_default="pending"))
        batch.add_column(sa.Column("migration_reason", sa.String(300), nullable=False,
                                   server_default=""))
        batch.create_index("ix_test_suite_scenario_id", ["scenario_id"])

    _migrate_suites()


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "DELETE FROM scenario WHERE origin = 'legacy_suite' "
        "AND id IN (SELECT scenario_id FROM test_suite WHERE migration_status = 'created')"
    ))

    with op.batch_alter_table("test_suite") as batch:
        batch.drop_index("ix_test_suite_scenario_id")
        batch.drop_column("migration_reason")
        batch.drop_column("migration_status")
        batch.drop_column("scenario_id")

    _rewrite_step_key("scenario", "scenario_id", "chain_id")

    with op.batch_alter_table("scenario") as batch:
        batch.drop_index("ix_scenario_status")
        batch.drop_index("ix_scenario_system")
        batch.drop_column("updated_at")
        batch.drop_column("origin")
        batch.drop_column("definition_version")
        batch.drop_column("status")

    op.rename_table("scenario", "chain")
    op.create_index("ix_chain_system", "chain", ["system"])
