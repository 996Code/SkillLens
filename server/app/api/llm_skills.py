from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.fieldchange import extract_field_changes
from app.models import FieldChange, RecordingSession

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sessions/{session_id}/field-changes")
async def run_field_changes(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = extract_field_changes(db, session_id)
    return {"field_changes": len(rows)}


@router.get("/sessions/{session_id}/field-changes")
async def list_field_changes(session_id: str, db: Session = Depends(get_db)) -> list:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db.query(FieldChange).filter(FieldChange.session_id == session_id).all()
    return [{"api_template": r.api_template, "before_seq": r.before_seq,
             "after_seq": r.after_seq, "changes": r.changes} for r in rows]
