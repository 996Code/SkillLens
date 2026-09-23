import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RecordingSession

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SessionCreate(BaseModel):
    target_system: str = ""
    note: str = ""


@router.post("/sessions")
async def create_session(body: SessionCreate, db: Session = Depends(get_db)) -> dict:
    session_id = str(uuid.uuid4())
    db.add(RecordingSession(id=session_id, target_system=body.target_system, note=body.note))
    db.commit()
    return {"session_id": session_id}
