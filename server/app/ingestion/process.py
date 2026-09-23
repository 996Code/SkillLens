from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.signals import extract_state_signals
from app.ingestion.url_template import split_url, templatize_path
from app.ingestion.windows import build_windows
from app.models import RawEvent, SemanticAction


def summarize_api(event: dict) -> dict:
    payload = event.get("payload") or {}
    template, params = templatize_path(split_url(payload.get("url", ""))[0])
    return {
        "seq": event["seq"],
        "method": payload.get("method"),
        "template": template,
        "status": payload.get("status"),
        "duration": payload.get("duration"),
        "params": params,
    }


def process_session(db: Session, session_id: str) -> dict:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.seq)
    ).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind, "payload": r.payload or {}} for r in rows]
    windows = build_windows(events)

    db.query(SemanticAction).filter(SemanticAction.session_id == session_id).delete()
    for i, w in enumerate(windows):
        api_calls = [summarize_api(m) for m in w["members"]]
        state_signals = []
        for m, call in zip(w["members"], api_calls):
            for s in extract_state_signals((m.get("payload") or {}).get("resBody")):
                state_signals.append({"api": call["template"], **s})
        db.add(SemanticAction(
            session_id=session_id, window_seq=i,
            anchor_seq=w["anchor"]["seq"],
            anchor_type=(w["anchor"].get("payload") or {}).get("type", ""),
            target=(w["anchor"].get("payload") or {}).get("target"),
            api_calls=api_calls, state_signals=state_signals,
        ))
    db.commit()
    return {"windows": len(windows)}
