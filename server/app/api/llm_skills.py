from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.fieldchange import extract_field_changes
from app.learning.outcome import generate_assertions, verify_against_session
from app.learning.skill import induce_skill
from app.models import FieldChange, OutcomeAssertion, RecordingSession, Skill

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
    from app.api.baseline import _skill_source
    from app.models import Alignment
    sources = {sid: source for sid, source in db.execute(
        select(RecordingSession.id, RecordingSession.source)).all()}
    alignments = {a.id: a for a in db.query(Alignment).all()}

    def source_of(r: Skill) -> str:
        # 同 baseline._skill_source 取法：alignment 首个 session 的 source，缺省 demo
        alignment = alignments.get(r.alignment_id)
        for sid in (alignment.session_ids or [] if alignment else []):
            if sid in sources:
                return sources[sid] or "demo"
        return "demo"

    rows = db.query(Skill).order_by(Skill.id.desc()).all()
    return [{"id": r.id, "alignment_id": r.alignment_id, "name": r.name,
             "description": r.description, "status": r.status,
             "confidence": r.confidence, "evidence_count": r.evidence_count,
             "notes": r.notes, "source": source_of(r)} for r in rows]


@router.post("/skills/{skill_id}/assertions")
async def create_assertions(skill_id: int, db: Session = Depends(get_db)) -> dict:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    rows = generate_assertions(db, skill_id)
    return {"assertions": len(rows)}


@router.post("/assertions/{assertion_id}/verify")
async def verify_assertion(assertion_id: int, db: Session = Depends(get_db)) -> dict:
    assertion = db.get(OutcomeAssertion, assertion_id)
    if not assertion:
        raise HTTPException(status_code=404, detail="assertion not found")
    if not db.get(Skill, assertion.skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    return verify_against_session(db, assertion_id)


@router.get("/skills/{skill_id}/assertions")
async def list_assertions(skill_id: int, db: Session = Depends(get_db)) -> list:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    rows = db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).all()
    return [{"id": r.id, "skill_id": r.skill_id, "layer": r.layer, "kind": r.kind,
             "api_template": r.api_template, "payload": r.payload} for r in rows]
