"""AR2 ScenarioRun read + finish endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import auth
from app.db import SessionLocal
from app.models import ReplayRun, ScenarioRun

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _summary(run: ScenarioRun) -> dict:
    return {
        "id": run.id,
        "scenario_id": run.scenario_id,
        "definition_version": run.definition_version,
        "trigger": run.trigger,
        "executor": run.executor,
        "mode": run.mode,
        "status": run.status,
        "source_track": run.source_track,
        "confirm_side_effect": run.confirm_side_effect,
        "pass_count": run.pass_count,
        "fail_count": run.fail_count,
        "error_count": run.error_count,
        "shadow_count": run.shadow_count,
        "blocked_count": run.blocked_count,
        "total_count": run.total_count,
        "failure_summary": run.failure_summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/scenario-runs")
async def list_scenario_runs(
    scenario_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = db.query(ScenarioRun)
    if scenario_id is not None:
        q = q.filter(ScenarioRun.scenario_id == scenario_id)
    if status:
        q = q.filter(ScenarioRun.status == status)
    return [_summary(r) for r in q.order_by(
        ScenarioRun.id.desc()).limit(limit).all()]


@router.get("/scenario-runs/{run_id}")
async def get_scenario_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ScenarioRun, run_id)
    if not run:
        raise HTTPException(404, "scenario_run not found")
    children = db.query(
        ReplayRun.id, ReplayRun.skill_id, ReplayRun.status, ReplayRun.mode,
        ReplayRun.execution_index, ReplayRun.attempt, ReplayRun.failure_class,
        ReplayRun.duration_ms,
    ).filter(ReplayRun.scenario_run_id == run_id
    ).order_by(ReplayRun.execution_index, ReplayRun.attempt).all()
    out = _summary(run)
    out["definition_snapshot"] = run.definition_snapshot
    out["expectation_snapshot"] = run.expectation_snapshot or []
    out["runs"] = [{
        "id": c[0], "skill_id": c[1], "status": c[2], "mode": c[3],
        "execution_index": c[4], "attempt": c[5], "failure_class": c[6],
        "duration_ms": c[7],
    } for c in children]
    return out


class FinishIn(BaseModel):
    status: str = Field(pattern="^(pass|fail|error|shadow|aborted)$")


@router.post("/scenario-runs/{run_id}/finish",
             dependencies=[Depends(auth.require_role("reviewer", "admin"))])
async def finish_scenario_run(run_id: int, body: FinishIn,
                              db: Session = Depends(get_db)) -> dict:
    """extension 通道终态上报：相同终态幂等；冲突终态 409。

    计数由服务端从子 ReplayRun 推导（不信任插件汇总）。
    """
    from app.scenario import service

    run = db.get(ScenarioRun, run_id)
    if not run:
        raise HTTPException(404, "scenario_run not found")
    try:
        run = service.finish_scenario_run(db, run, body.status)
    except service.ConflictError as e:
        raise HTTPException(409, str(e))
    # 服务端推导计数：有效结果=每 execution_index 的最高 attempt
    children = db.query(ReplayRun).filter(
        ReplayRun.scenario_run_id == run_id).all()
    best: dict[int, ReplayRun] = {}
    for c in children:
        idx = c.execution_index if c.execution_index is not None else -1
        cur = best.get(idx)
        if cur is None or c.attempt > cur.attempt:
            best[idx] = c
    statuses = [c.status for c in best.values()]
    snap_steps = (run.definition_snapshot or {}).get("steps") or []
    blocked = max(0, len(snap_steps) - len(statuses))
    service.recompute_counts(db, run, blocked, statuses)
    db.commit()
    db.refresh(run)
    return _summary(run)
