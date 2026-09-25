from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReplayRun, Skill
from app.replay.runner import run_replay, run_replay_batch

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ReplayRequest(BaseModel):
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/skills/{skill_id}/replay")
async def replay(skill_id: int, body: ReplayRequest, db: Session = Depends(get_db)) -> dict:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    run = await run_replay(db, skill_id, body.overrides, body.confirm_side_effect)
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path}


class ReplayBatchRequest(BaseModel):
    skill_ids: list[int] = Field(min_length=1)  # 空列表 → 422
    overrides_map: dict[int, dict] = {}         # 按 skill_id 给 overrides，缺省空
    confirm_side_effect: bool = False           # C1：批级门控参数


@router.post("/skills/replay-batch")
async def replay_batch(body: ReplayBatchRequest,
                       db: Session = Depends(get_db)) -> dict:
    """S13 F3 批回放：browser 实例复用（一次 launch 多 context 串行），
    confirm_side_effect 批级——false 时各 skill 独立走 shadow 门控。"""
    runs = await run_replay_batch(db, body.skill_ids, body.overrides_map,
                                  body.confirm_side_effect)
    results = [{"skill_id": r.skill_id, "run_id": r.id,
                "status": r.status, "mode": r.mode} for r in runs]
    return {"results": results, "total": len(results),
            "pass_count": sum(1 for r in results if r["status"] == "pass"),
            "fail_count": sum(1 for r in results if r["status"] == "fail"),
            "error_count": sum(1 for r in results if r["status"] == "error")}


@router.get("/replay-runs/{run_id}")
async def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path}
