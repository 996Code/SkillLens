from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.signals import extract_state_signals
from app.ingestion.url_template import split_url, templatize_path
from app.ingestion.windows import IDLE_MS, MAX_WINDOW_MS, build_windows
from app.models import NormalizedEvent, RawEvent, SemanticAction, TransactionWindow


def normalize_event(e: dict) -> str:
    payload = e.get("payload") or {}
    kind = e["kind"]
    if kind == "action":
        label = (payload.get("target") or {}).get("label", "")
        return f"{payload.get('type', kind)}:{label}"
    if kind == "network":
        path, _ = split_url(payload.get("url", ""))
        template, _ = templatize_path(path)
        return f"{payload.get('method', 'GET')}:{template}"
    return kind


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
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    events = [{"event_id": r.id, "seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}, "page_id": r.page_id or ""} for r in rows]
    windows = build_windows(events)

    for model in (NormalizedEvent, TransactionWindow, SemanticAction):
        db.query(model).filter(model.session_id == session_id).delete()

    for e in events:
        db.add(NormalizedEvent(session_id=session_id, event_id=e["event_id"],
                               template=normalize_event(e), page_id=e["page_id"],
                               seq=e["seq"], ts=e["ts"]))

    for i, w in enumerate(windows):
        member_ids = [m["event_id"] for m in w["members"]]
        db.add(TransactionWindow(session_id=session_id, window_seq=i,
                                 anchor_event_id=w["anchor"]["event_id"],
                                 member_event_ids=member_ids,
                                 idle_ms=IDLE_MS, max_window_ms=MAX_WINDOW_MS))
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
