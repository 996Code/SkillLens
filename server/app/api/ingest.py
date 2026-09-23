from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.alignment import align_skeletons
from app.ingestion.process import load_windows, process_session
from app.ingestion.variables import input_variables, param_variables
from app.models import Alignment, RawEvent, RecordingSession, SemanticAction
from app.schemas import AlignRequest

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


@router.post("/align")
async def align(body: AlignRequest, db: Session = Depends(get_db)) -> dict:
    for sid in body.session_ids:
        if not db.get(RecordingSession, sid):
            raise HTTPException(status_code=404, detail=f"session {sid} not found")
        if db.query(SemanticAction).filter(SemanticAction.session_id == sid).count() == 0:
            raise HTTPException(status_code=409, detail="session not processed")
    windows_per_session = [(sid, load_windows(db, sid)) for sid in body.session_ids]
    skeleton = align_skeletons(windows_per_session)
    pvars = param_variables(skeleton, windows_per_session)
    events_per_session = []
    for sid, _ in windows_per_session:
        rows = db.execute(
            select(RawEvent).where(RawEvent.session_id == sid).order_by(RawEvent.ts, RawEvent.seq)
        ).scalars().all()
        events_per_session.append((sid, [{"kind": r.kind, "payload": r.payload or {}} for r in rows]))
    ivars = input_variables(events_per_session)
    row = Alignment(session_ids=body.session_ids, skeleton=skeleton,
                    param_variables=pvars, input_variables=ivars)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"alignment_id": row.id, "skeleton": skeleton,
            "param_variables": pvars, "input_variables": ivars}


@router.get("/alignments/{alignment_id}")
async def get_alignment(alignment_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Alignment, alignment_id)
    if not row:
        raise HTTPException(status_code=404, detail="alignment not found")
    return {"alignment_id": row.id, "session_ids": row.session_ids,
            "skeleton": row.skeleton, "param_variables": row.param_variables,
            "input_variables": row.input_variables}
