import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.url_template import split_url, templatize_path
from app.models import FieldChange, RawEvent


def extract_field_changes(db: Session, session_id: str) -> list[FieldChange]:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    posts: dict[str, list[tuple[int, dict]]] = {}
    for r in rows:
        p = r.payload or {}
        if r.kind != "network" or p.get("method") != "POST" or not p.get("reqBody"):
            continue
        try:
            body = json.loads(p["reqBody"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(body, dict):
            continue
        template, _ = templatize_path(split_url(p.get("url", ""))[0])
        posts.setdefault(template, []).append((r.seq, body))

    db.query(FieldChange).filter(FieldChange.session_id == session_id).delete()
    written: list[FieldChange] = []
    from app.ingestion.fielddiff import diff_bodies
    for template, seqs in posts.items():
        if len(seqs) < 2:
            continue
        (b_seq, b_body), (a_seq, a_body) = seqs[-2], seqs[-1]
        changes = diff_bodies(b_body, a_body)
        if not changes:
            continue
        row = FieldChange(session_id=session_id, api_template=template,
                          before_seq=b_seq, after_seq=a_seq, changes=changes)
        db.add(row)
        written.append(row)
    db.commit()
    return written
