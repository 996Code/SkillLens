"""AP3 discovery flow API: segment ambient sessions, human review gate."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import WRITE_GUARD
from app.db import SessionLocal
from app.models import (DiscoveredFlow, RawEvent, RecordingSession,
                         Scenario, Skill)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _summary(row: DiscoveredFlow) -> dict:
    events = row.events or []
    return {
        "id": row.id, "session_id": row.session_id,
        "status": row.status, "discard_reason": row.discard_reason,
        "has_write": row.has_write, "skill_id": row.skill_id,
        "event_count": len(events),
        "created_at": row.created_at.isoformat(),
    }


@router.post("/sessions/{session_id}/segment", dependencies=WRITE_GUARD)
async def segment_session_endpoint(session_id: str,
                                    db: Session = Depends(get_db)) -> dict:
    """AP3：ambient 会话切分——过闸段进待发现；discard 段留痕（C3）。"""
    sess = db.get(RecordingSession, session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    if sess.source != "ambient":
        raise HTTPException(422, "仅 ambient 会话可切分（显式录制本就是单任务）")
    # 幂等：已切分过的会话不重复
    if db.query(DiscoveredFlow).filter(
            DiscoveredFlow.session_id == session_id).count() > 0:
        raise HTTPException(409, "该会话已切分")

    from app.learning.segment import segment_session, GateConfig
    rows = db.execute(select(RawEvent).where(
        RawEvent.session_id == session_id)
        .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}} for r in rows]
    segments = segment_session(events, GateConfig())

    flows = discarded = 0
    for seg in segments:
        row = DiscoveredFlow(
            session_id=session_id, events=seg["events"],
            has_write=seg.get("has_write", False),
            status="auto_discarded" if seg.get("discarded") else "pending",
            discard_reason=seg.get("discard_reason", ""))
        db.add(row)
        if seg.get("discarded"):
            discarded += 1
        else:
            flows += 1
    db.commit()
    return {"flows": flows, "discarded": discarded,
            "total_segments": len(segments)}


@router.get("/discovered-flows")
async def list_flows(status: str = Query(default=""),
                     db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(DiscoveredFlow)
    if status:
        q = q.filter(DiscoveredFlow.status == status)
    return [_summary(r) for r in q.order_by(
        DiscoveredFlow.id.desc()).limit(100).all()]


async def _confirm_flow(db: Session, flow: DiscoveredFlow) -> DiscoveredFlow:
    """确认：段事件复制成新会话 → 既有 process→align→induce 管道。"""
    # ① 新会话（ambient 源——C2 分轨延续）
    new_sid = str(uuid.uuid4())
    src = db.get(RecordingSession, flow.session_id)
    db.add(RecordingSession(id=new_sid, target_system=src.target_system if src else "",
                            note="发现流确认", source="ambient"))
    db.flush()
    for i, e in enumerate(flow.events or []):
        db.add(RawEvent(session_id=new_sid, seq=i, ts=e.get("ts", i),
                        page_id=e.get("page_id", ""), kind=e.get("kind", ""),
                        payload=e.get("payload") or {}))
    db.commit()

    # ② 既有管道：process → align → induce（LLM 命名）
    from app.ingestion.process import process_session, load_windows
    from app.ingestion.alignment import align_skeletons
    from app.ingestion.variables import param_variables, input_variables
    from app.learning.skill import induce_skill
    from app.models import Alignment

    process_session(db, new_sid)
    windows = load_windows(db, new_sid)
    aligned = align_skeletons([(new_sid, windows)])
    ev_rows = db.execute(select(RawEvent).where(
        RawEvent.session_id == new_sid).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    events_per_session = [(new_sid, [{"kind": r.kind, "payload": r.payload or {}}
                                      for r in ev_rows])]
    alignment = Alignment(
        session_ids=[new_sid], skeleton=aligned["skeleton"],
        param_variables=param_variables(aligned["skeleton"], [(new_sid, windows)]),
        input_variables=input_variables(events_per_session),
        window_params={}, buckets=aligned["buckets"])
    db.add(alignment)
    db.commit()
    db.refresh(alignment)

    skill = await induce_skill(db, alignment.id)
    flow.status = "confirmed"
    flow.skill_id = skill.id
    db.commit()
    db.refresh(flow)
    return flow


@router.post("/discovered-flows/{flow_id}/confirm", dependencies=WRITE_GUARD)
async def confirm_flow(flow_id: int, db: Session = Depends(get_db)) -> dict:
    flow = db.get(DiscoveredFlow, flow_id)
    if not flow:
        raise HTTPException(404, "flow not found")
    if flow.status != "pending":
        raise HTTPException(409, f"流状态 {flow.status} 不可确认")
    try:
        flow = await _confirm_flow(db, flow)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"确认失败：{str(e)[:200]}")
    out = _summary(flow)
    skill = db.get(Skill, flow.skill_id) if flow.skill_id else None
    out["skill_name"] = skill.name if skill else None
    return out


@router.post("/discovered-flows/{flow_id}/discard", dependencies=WRITE_GUARD)
async def discard_flow(flow_id: int, db: Session = Depends(get_db)) -> dict:
    flow = db.get(DiscoveredFlow, flow_id)
    if not flow:
        raise HTTPException(404, "flow not found")
    if flow.status != "pending":
        raise HTTPException(409, f"流状态 {flow.status} 不可丢弃")
    flow.status = "discarded"
    flow.discard_reason = "user_discarded"
    db.commit()
    db.refresh(flow)
    return _summary(flow)
