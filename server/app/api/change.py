from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.change.expected import generate_expected_delta, verify_delta
from app.db import SessionLocal
from app.models import ExpectedDelta, ReplayRun

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CreateDeltaRequest(BaseModel):
    requirement_id: str
    requirement_text: str


class ConfirmRequest(BaseModel):
    reviewed_by: str
    changes: list[dict] | None = None


@router.post("/expected-deltas", status_code=201)
async def create_expected(body: CreateDeltaRequest, db: Session = Depends(get_db)) -> dict:
    row = generate_expected_delta(db, body.requirement_text, body.requirement_id)
    return {"id": row.id, "status": row.status, "changes": row.changes, "notes": row.notes}


@router.post("/expected-deltas/{delta_id}/confirm")
async def confirm_expected(delta_id: int, body: ConfirmRequest,
                           db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    if row.status == "confirmed":
        raise HTTPException(409, "已确认过，不可重复确认")
    if body.changes is not None:
        ok, why = verify_delta(body.changes)
        if not ok:
            raise HTTPException(422, why)
        row.changes = body.changes
    row.status = "confirmed"
    row.reviewed_by = body.reviewed_by
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": row.status, "changes": row.changes}


class ObserveRequest(BaseModel):
    skill_id: int
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/expected-deltas/{delta_id}/observe", status_code=201)
async def observe(delta_id: int, body: ObserveRequest,
                  db: Session = Depends(get_db)) -> dict:
    from app.change.observed import run_observe
    try:
        row = await run_observe(db, delta_id, body.skill_id,
                                body.overrides, body.confirm_side_effect)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return {"id": row.id, "items": row.items, "replay_run_id": row.replay_run_id,
            "replay_status": db.get(ReplayRun, row.replay_run_id).status}


@router.get("/expected-deltas/{delta_id}")
async def get_expected(delta_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    return {"id": row.id, "requirement_id": row.requirement_id,
            "feature": row.feature, "changes": row.changes, "status": row.status,
            "reviewed_by": row.reviewed_by, "notes": row.notes}
