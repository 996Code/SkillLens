from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.fieldchange import extract_field_changes
from app.learning.skill import induce_skill
from app.models import FieldChange, RecordingSession, Skill

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


@router.post("/alignments/{alignment_id}/induce")
async def induce(alignment_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models import Alignment
    if not db.get(Alignment, alignment_id):
        raise HTTPException(status_code=404, detail="alignment not found")
    skill = induce_skill(db, alignment_id)
    return {"id": skill.id, "alignment_id": skill.alignment_id, "name": skill.name,
            "description": skill.description, "status": skill.status,
            "skeleton": skill.skeleton, "param_variables": skill.param_variables,
            "input_variables": skill.input_variables, "confidence": skill.confidence,
            "evidence_count": skill.evidence_count, "notes": skill.notes}


@router.get("/skills")
async def list_skills(db: Session = Depends(get_db)) -> list:
    rows = db.query(Skill).order_by(Skill.id.desc()).all()
    return [{"id": r.id, "alignment_id": r.alignment_id, "name": r.name,
             "description": r.description, "status": r.status,
             "confidence": r.confidence, "evidence_count": r.evidence_count,
             "notes": r.notes} for r in rows]
