from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReplayRun, Skill
from app.replay.runner import run_replay

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


@router.get("/replay-runs/{run_id}")
async def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path}
