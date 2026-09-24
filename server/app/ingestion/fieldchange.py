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
        posts.setdefault(template, []).append((r.seq, body, p["reqBody"]))

    db.query(FieldChange).filter(FieldChange.session_id == session_id).delete()
    written: list[FieldChange] = []
    from app.ingestion.fielddiff import cap_value, diff_bodies, truncate_req_body
    for template, seqs in posts.items():
        if len(seqs) < 2:
            continue
        (b_seq, b_body, b_raw), (a_seq, a_body, a_raw) = seqs[-2], seqs[-1]
        b_tr = truncate_req_body(b_raw)
        a_tr = truncate_req_body(a_raw)
        # diff 在截断文本上做；截断点若切断 JSON 致解析失败，回退用原文
        # 解析出的 body（diff 语义降级，但全文绝不入 changes——值另有 cap 保护）
        b_eff = _truncated_body(b_tr["text"]) if b_tr["truncated"] else b_body
        a_eff = _truncated_body(a_tr["text"]) if a_tr["truncated"] else a_body
        if b_eff is None or a_eff is None:
            b_eff, a_eff = b_body, a_body
        changes = diff_bodies(b_eff, a_eff)
        if b_tr["truncated"] or a_tr["truncated"]:
            # 截断标记进入已有 changes JSON 列（不加列）
            changes.append({
                "field": "_truncated",
                "truncated": True,
                "sha256": {"before": b_tr["sha256"], "after": a_tr["sha256"]},
            })
        if not changes:
            continue
        for ch in changes:
            ch["before"] = cap_value(ch.get("before"))
            ch["after"] = cap_value(ch.get("after"))
        row = FieldChange(session_id=session_id, api_template=template,
                          before_seq=b_seq, after_seq=a_seq, changes=changes)
        db.add(row)
        written.append(row)
    db.commit()
    return written


def _truncated_body(text: str) -> dict | None:
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None
