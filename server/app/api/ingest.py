from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.process import process_session
from app.models import RecordingSession, SemanticAction

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sessions/{session_id}/process")
async def process(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return process_session(db, session_id)


@router.get("/sessions/{session_id}/semantic-actions")
async def list_semantic_actions(session_id: str, db: Session = Depends(get_db)) -> list:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db.query(SemanticAction).filter(
        SemanticAction.session_id == session_id
    ).order_by(SemanticAction.window_seq).all()
    return [
        {"window_seq": r.window_seq, "anchor_seq": r.anchor_seq,
         "anchor_type": r.anchor_type, "target": r.target,
         "api_calls": r.api_calls, "state_signals": r.state_signals}
        for r in rows
    ]
