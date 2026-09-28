"""S10.5 块M 链路审计端点（M1~M4，全只读）：C3「可审计」的数据载体。

- GET /audit/sessions            会话列表（source/note/事件数/过滤数/语义动作数）
- GET /audit/evidence-edges      证据边列表（type 精确 / src_like 模糊过滤）
- GET /audit/llm-logs            LLM 调用日志（prompt/response 200 字符界面摘要，
                                 完整审计走 DB——llm_call_log 不经此端点全量外泄）
- GET /audit/sessions/{sid}/trace 单会话链路下钻：窗口（kept/reason，M4）→
  语义动作（前后快照 forms 计数）→ 对齐（骨架/分桶）→ Skill → 回放历史

只读端点，无写路径；counts 用 GROUP BY 聚合一次查询（无数据为 0）。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Alignment,
    EvidenceEdge,
    FilteredWindow,
    LlmCallLog,
    RawEvent,
    RecordingSession,
    ReplayRun,
    SemanticAction,
    Skill,
    TransactionWindow,
)

router = APIRouter()

# M3：界面摘要截断（完整 prompt/response 审计走 DB 直查）
HEAD_CHARS = 200


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _counts(db: Session) -> dict[str, dict[str, int]]:
    """session_id -> {event_count, filtered_count, semantic_action_count}。

    三计数各一条 GROUP BY 聚合查询（无数据的会话不出现 → 调用侧 get 0）。
    """
    out: dict[str, dict[str, int]] = {}

    def _merge(model, key: str) -> None:
        rows = db.execute(
            select(model.session_id, func.count()).group_by(model.session_id)
        ).all()
        for sid, n in rows:
            out.setdefault(sid, {})[key] = n

    _merge(RawEvent, "event_count")
    _merge(FilteredWindow, "filtered_count")
    _merge(SemanticAction, "semantic_action_count")
    return out


def _session_item(session: RecordingSession, counts: dict[str, dict[str, int]]) -> dict:
    c = counts.get(session.id, {})
    return {
        "session_id": session.id,
        "source": session.source,
        "note": session.note,
        "created_at": session.started_at.isoformat(),
        "event_count": c.get("event_count", 0),
        "filtered_count": c.get("filtered_count", 0),
        "semantic_action_count": c.get("semantic_action_count", 0),
    }


@router.get("/audit/sessions")
async def list_sessions(limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)) -> list:
    counts = _counts(db)
    sessions = db.query(RecordingSession).order_by(
        RecordingSession.started_at.desc()).limit(limit).all()
    return [_session_item(s, counts) for s in sessions]


@router.get("/audit/evidence-edges")
async def list_evidence_edges(type: str | None = None, src_like: str | None = None,
                              limit: int = Query(200, ge=1, le=1000),
                              db: Session = Depends(get_db)) -> list:
    q = db.query(EvidenceEdge)
    if type:
        q = q.filter(EvidenceEdge.type == type)
    if src_like:
        q = q.filter(EvidenceEdge.src.like(f"%{src_like}%"))
    rows = q.order_by(EvidenceEdge.evidence_count.desc()).limit(limit).all()
    return [{"src": r.src, "dst": r.dst, "type": r.type,
             "evidence_count": r.evidence_count,
             "first_seen": r.first_seen.isoformat(),
             "last_seen": r.last_seen.isoformat()} for r in rows]


@router.get("/audit/llm-logs")
async def list_llm_logs(limit: int = Query(50, ge=1, le=1000), db: Session = Depends(get_db)) -> list:
    rows = db.query(LlmCallLog).order_by(LlmCallLog.id.desc()).limit(limit).all()
    return [{"id": r.id, "purpose": r.purpose, "provider": r.provider,
             "model": r.model, "prompt_tokens": r.prompt_tokens,
             "completion_tokens": r.completion_tokens,
             "latency_ms": r.latency_ms,
             "created_at": r.created_at.isoformat(),
             "prompt_head": (r.prompt or "")[:HEAD_CHARS],
             "response_head": (r.response or "")[:HEAD_CHARS]} for r in rows]


@router.get("/audit/llm-logs/{log_id}")
async def llm_log_detail(log_id: int, db: Session = Depends(get_db)) -> dict:
    # S32：链路可视化需要单条调用的完整 prompt/response（区别于列表 200 字符摘要）。
    # 按需单条取用，不经列表端点全量外泄；鉴权同 audit 路由组（require_user）。
    row = db.get(LlmCallLog, log_id)
    if not row:
        raise HTTPException(status_code=404, detail="llm log not found")
    return {"id": row.id, "purpose": row.purpose, "provider": row.provider,
            "model": row.model, "prompt": row.prompt or "",
            "response": row.response or "",
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "latency_ms": row.latency_ms,
            "created_at": row.created_at.isoformat()}


def _forms_count(snapshot: dict | None) -> int | None:
    """快照 forms 计数；无快照（旧数据/未采集）为 None。"""
    if snapshot is None:
        return None
    return len(snapshot.get("forms") or [])


@router.get("/audit/sessions/{session_id}/trace")
async def session_trace(session_id: str, db: Session = Depends(get_db)) -> dict:
    session = db.get(RecordingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    counts = _counts(db)

    # 窗口层（M4）：transaction_window 全窗 LEFT JOIN filtered_window 决策
    windows = db.query(TransactionWindow).filter(
        TransactionWindow.session_id == session_id
    ).order_by(TransactionWindow.window_seq).all()
    filtered = {r.window_seq: r.reason for r in db.query(FilteredWindow).filter(
        FilteredWindow.session_id == session_id).all()}
    actions = {r.window_seq: r for r in db.query(SemanticAction).filter(
        SemanticAction.session_id == session_id).all()}
    anchor_ids = [w.anchor_event_id for w in windows]
    raw_anchors = {r.id: r for r in db.query(RawEvent).filter(
        RawEvent.id.in_(anchor_ids)).all()} if anchor_ids else {}

    window_items = []
    for w in windows:
        sa = actions.get(w.window_seq)
        if sa is not None:
            anchor_type = sa.anchor_type
            anchor_label = (sa.target or {}).get("label")
            api_count = len(sa.api_calls or [])
            state_signal_count = len(sa.state_signals or [])
            has_state_snapshot = bool(sa.state_before or sa.state_after)
        else:
            # 过滤窗无 semantic_action：anchor 信息回退 raw_event（anchor_event_id）
            payload = (raw_anchors.get(w.anchor_event_id).payload or {}
                       if raw_anchors.get(w.anchor_event_id) else {})
            anchor_type = payload.get("type", "")
            anchor_label = (payload.get("target") or {}).get("label")
            api_count = 0
            state_signal_count = 0
            has_state_snapshot = False
        window_items.append({
            "window_seq": w.window_seq,
            "anchor_type": anchor_type,
            "anchor_label": anchor_label,
            "kept": w.window_seq not in filtered,
            "filter_reason": filtered.get(w.window_seq, ""),
            "api_count": api_count,
            "state_signal_count": state_signal_count,
            "has_state_snapshot": has_state_snapshot,
        })

    # 语义动作层：forms 计数（快照明细走 semantic-actions 端点，此处为概要）
    action_items = [{
        "window_seq": sa.window_seq,
        "anchor_label": (sa.target or {}).get("label"),
        "api_templates": [c.get("template") for c in sa.api_calls or []],
        "state_before_forms": _forms_count(sa.state_before),
        "state_after_forms": _forms_count(sa.state_after),
    } for sa in sorted(actions.values(), key=lambda r: r.window_seq)]

    # 下钻下游：alignment（session_ids JSON 列，Python 侧包含过滤）→ skill → replay
    alignments = [a for a in db.query(Alignment.id, Alignment.session_ids,
                                           Alignment.skeleton, Alignment.buckets).all()
                  if session_id in (a.session_ids or [])]
    alignment_items = [{
        "id": a.id,
        "skeleton_steps": len(a.skeleton or []),
        "bucket_count": len(a.buckets) if a.buckets else 1,
    } for a in alignments]

    alignment_ids = [a.id for a in alignments]
    skills = (db.query(Skill).filter(Skill.alignment_id.in_(alignment_ids)).all()
              if alignment_ids else [])
    # S15：skills 段默认排除 superseded（历史版本不进链路视图）；
    # replay_runs 段仍取全量 skill（含 superseded）——C3 审计不丢历史
    skill_items = [{"id": s.id, "name": s.name, "status": s.status,
                    "confidence": s.confidence}
                   for s in skills if s.status != "superseded"]

    skill_ids = [s.id for s in skills]
    runs = (db.query(ReplayRun).filter(ReplayRun.skill_id.in_(skill_ids))
            .order_by(ReplayRun.id.desc()).all() if skill_ids else [])
    run_items = [{"id": r.id, "status": r.status, "mode": r.mode,
                  "created_at": r.created_at.isoformat()} for r in runs]

    return {
        "session": _session_item(session, counts),
        "windows": window_items,
        "semantic_actions": action_items,
        "alignments": alignment_items,
        "skills": skill_items,
        "replay_runs": run_items,
    }
