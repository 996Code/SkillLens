from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.noise_filter import classify_windows
from app.ingestion.signals import extract_state_signals
from app.ingestion.url_template import split_url, templatize_path
from app.ingestion.windows import IDLE_MS, MAX_WINDOW_MS, build_windows
from app.models import FilteredWindow, NormalizedEvent, RawEvent, SemanticAction, TransactionWindow


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


def _events_of(db: Session, session_id: str) -> list[dict]:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    return [{"event_id": r.id, "seq": r.seq, "ts": r.ts, "kind": r.kind,
             "payload": r.payload or {}, "page_id": r.page_id or ""} for r in rows]


def load_windows(db: Session, session_id: str) -> list[dict]:
    return build_windows(_events_of(db, session_id))


def assign_snapshots(events: list[dict], windows: list[dict]) -> list[dict]:
    """把 kind="snapshot" 事件按时间序归属到锚点窗口（Sprint 8 块B）。

    归属规则（与 CS 采集时序一致，见 extension capture.ts）：
    - before 快照 ts 早于锚点、且晚于上一锚点（动作前同步采集）→ 归该锚点窗口，
      多 before 取最靠近锚点的一个；
    - after 快照在锚点之后、下一锚点之前（锚点后 2.5s 采集，跨网络空闲窗口）→
      归该锚点窗口，多 after 取最后；
    - 无快照成员时 state_before/state_after 为 None（向后兼容旧数据）。
    snapshot 不进窗口 members（members 只含 network，被 window_signature/
    summarize_api 消费，混入会污染对齐骨架与 api_calls）。"""
    anchor_ts = [w["anchor"]["ts"] for w in windows]
    out: list[dict] = [{"before": None, "after": None} for _ in windows]
    for e in events:
        if e["kind"] != "snapshot":
            continue
        payload = e.get("payload") or {}
        phase = payload.get("phase")
        if phase not in ("before", "after"):
            continue
        # 归属窗口：before 先于锚点采集 → 归属下一个锚点（首个 ts >= 快照 ts 的窗口）；
        # after 晚于锚点 → 归属前一个锚点（最后一个 ts <= 快照 ts 的窗口）。
        # 同窗口多 before/after 时后者覆盖前者（before 取最靠近锚点，after 取最后）。
        idx = None
        if phase == "before":
            for i, ts in enumerate(anchor_ts):
                if e["ts"] <= ts:
                    idx = i
                    break
        else:
            for i, ts in enumerate(anchor_ts):
                if e["ts"] >= ts:
                    idx = i
        if idx is None:
            continue  # 末锚点后才有的 before / 首锚点前的 after：时序异常，丢弃
        out[idx][phase] = payload
    return out


def process_session(db: Session, session_id: str) -> dict:
    events = _events_of(db, session_id)
    windows = build_windows(events)
    snapshots = assign_snapshots(events, windows)
    # S10 Task2：噪声过滤——快照归属一并交给分类器（孤儿点击判定需要它）
    for i, w in enumerate(windows):
        w["snapshots"] = [s for s in (snapshots[i]["before"], snapshots[i]["after"]) if s]
    decisions = classify_windows(windows)

    for model in (NormalizedEvent, TransactionWindow, SemanticAction, FilteredWindow):
        db.query(model).filter(model.session_id == session_id).delete()

    for e in events:
        db.add(NormalizedEvent(session_id=session_id, event_id=e["event_id"],
                               template=normalize_event(e), page_id=e["page_id"],
                               seq=e["seq"], ts=e["ts"]))

    kept = 0
    for i, w in enumerate(windows):
        member_ids = [m["event_id"] for m in w["members"]]
        db.add(TransactionWindow(session_id=session_id, window_seq=i,
                                 anchor_event_id=w["anchor"]["event_id"],
                                 member_event_ids=member_ids,
                                 idle_ms=IDLE_MS, max_window_ms=MAX_WINDOW_MS))
        d = decisions[i]
        if not d["kept"]:
            # C3：kept=False 不生成 semantic_action，但决策落库可审计可回放
            db.add(FilteredWindow(session_id=session_id, window_seq=i, reason=d["reason"]))
            continue
        kept += 1
        api_calls = [summarize_api(m) for m in w["members"]]
        state_signals = []
        for m, call in zip(w["members"], api_calls):
            for s in extract_state_signals((m.get("payload") or {}).get("resBody")):
                state_signals.append({"api": call["template"], **s})
        snaps = snapshots[i]
        db.add(SemanticAction(
            session_id=session_id, window_seq=i,
            anchor_seq=w["anchor"]["seq"],
            anchor_type=(w["anchor"].get("payload") or {}).get("type", ""),
            target=(w["anchor"].get("payload") or {}).get("target"),
            api_calls=api_calls, state_signals=state_signals,
            state_before=snaps["before"], state_after=snaps["after"],
        ))
    db.commit()
    return {"windows": len(windows), "kept": kept}
