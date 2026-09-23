import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RawEvent, RecordingSession
from app.schemas import RawEventIn

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


@router.post("/sessions/{session_id}/events")
async def ingest_events(session_id: str, events: list[RawEventIn],
                        db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        db.add_all(RawEvent(session_id=session_id, seq=e.seq, page_id=e.page_id,
                            ts=e.ts, kind=e.kind, payload=e.payload) for e in events)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="duplicate (session_id, page_id, seq)")
    return {"accepted": len(events)}
