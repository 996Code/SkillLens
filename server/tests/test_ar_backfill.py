"""AR6 backfill script tests: deterministic failure-class recomputation."""
import json

from app.db import SessionLocal
from app.models import ReplayRun


def _mk(db, **kw) -> int:
    row = ReplayRun(
        skill_id=kw.get("skill_id", 1),
        mode=kw.get("mode", "execute"),
        status=kw.get("status", "fail"),
        plan=kw.get("plan", {"steps": []}),
        executed=kw.get("executed"),
        assertion_results=kw.get("assertion_results"),
        attribution=kw.get("attribution"),
        failure_class=kw.get("failure_class"),
        scope_kind=kw.get("scope_kind", "legacy_unscoped"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


async def test_only_provable_runs_are_reclassified(client):
    """回填只改 fail/error 行的 failure_class；pass 行不动。"""
    db = SessionLocal()
    try:
        fail_id = _mk(db, status="fail",
                      attribution="Page.goto: net::ERR_CONNECTION_REFUSED")
        from app.models import ReplayRun as RR
        pass_id = _mk(db, status="pass")
        pass_before = db.get(RR, pass_id).failure_class
        fail_row_probe = db.get(RR, fail_id)
        assert fail_row_probe is not None and fail_row_probe.id == fail_id
    finally:
        db.close()

    from scripts.ar_backfill import backfill_failure_classes
    stats = backfill_failure_classes(SessionLocal(), dry_run=False)
    assert stats["processed"] >= 1, stats
    assert stats["changed"] >= 1, stats
    assert stats["by_class"].get("e1_env", 0) >= 1, stats

    db = SessionLocal()
    try:
        from app.models import ReplayRun as RR2
        fail_row = db.get(RR2, fail_id)
        assert fail_row is not None, f"行 {fail_id} 不见了"
        assert fail_row.failure_class == "e1_env", fail_row.failure_class
        pass_row = db.get(RR2, pass_id)
        assert pass_row.failure_class == pass_before
    finally:
        db.close()


async def test_backfill_never_guesses_expected_failure(client):
    """无证据行保留 unclassified——不猜 e4。"""
    db = SessionLocal()
    try:
        bare_id = _mk(db, status="fail", attribution=None,
                      plan={"steps": []}, executed=None,
                      assertion_results=None)
    finally:
        db.close()

    from scripts.ar_backfill import backfill_failure_classes
    backfill_failure_classes(SessionLocal(), dry_run=False)

    db = SessionLocal()
    try:
        row = db.get(ReplayRun, bare_id)
        assert row.failure_class is None, "无确定性证据不得猜分类"
    finally:
        db.close()


async def test_rerun_is_idempotent(client):
    db = SessionLocal()
    try:
        _mk(db, status="fail",
            attribution="登录页跳转 /login 环境失败")
    finally:
        db.close()
    from scripts.ar_backfill import backfill_failure_classes
    s1 = backfill_failure_classes(SessionLocal(), dry_run=False)
    s2 = backfill_failure_classes(SessionLocal(), dry_run=False)
    assert s2["changed"] == 0, "二次回填零变更（幂等）"
    assert s1["processed"] >= 1
