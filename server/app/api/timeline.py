"""S32 链路时间线：按时间聚合所有环节，统一可视化入口。

GET /api/v1/timeline → 按时间倒序的执行链路列表：
- session: 采集会话（事件数/语义动作数）
- alignment: 对齐（骨架）
- skill: Skill 学习（LLM 命名）
- replay: 回放（步骤/断言/耗时）
- report: 四分类报告
- review: 评审
- llm: LLM 调用（purpose/prompt/response/tokens/latency）
- agent_run: 夜间运行（node_outputs）

每项含：id/type/title/detail/ts + 可展开的 detail_url
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (AgentRun, Alignment, DeltaReport, LlmCallLog,
                        RecordingSession, ReplayRun, Review, Skill)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/timeline")
async def get_timeline(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list:
    items: list[dict] = []

    # 采集会话（事件/语义计数从关联表聚合）
    from app.models import RawEvent, SemanticAction
    from sqlalchemy import func
    for s in db.query(RecordingSession).order_by(
            RecordingSession.started_at.desc()).limit(limit).all():
        ev = db.query(func.count(RawEvent.id)).filter(
            RawEvent.session_id == s.id).scalar() or 0
        sa = db.query(func.count(SemanticAction.id)).filter(
            SemanticAction.session_id == s.id).scalar() or 0
        items.append({
            "type": "session", "id": s.id, "title": f"采集 {s.id[:8]}",
            "subtitle": f"事件 {ev} · 语义 {sa} · {s.note or ''}",
            "ts": s.started_at.isoformat(),
        })

    # 对齐
    for a in db.query(Alignment).order_by(
            Alignment.created_at.desc()).limit(limit).all():
        skel_count = len(a.skeleton or [])
        items.append({
            "type": "alignment", "id": a.id, "title": f"对齐 #{a.id}",
            "subtitle": f"骨架 {skel_count} 步 · 会话 {len(a.session_ids)}",
            "ts": (a.created_at or datetime.utcnow()).isoformat(),
        })

    # Skill 学习
    for s in db.query(Skill).order_by(
            Skill.created_at.desc()).limit(limit).all():
        items.append({
            "type": "skill", "id": s.id, "title": f"Skill #{s.id} {s.name}",
            "subtitle": f"{s.status} · 置信度 {s.confidence:.0%} · 证据 {s.evidence_count}",
            "ts": s.created_at.isoformat(),
        })

    # 回放
    for r in db.query(ReplayRun).order_by(
            ReplayRun.created_at.desc()).limit(limit).all():
        steps = len((r.executed or []))
        asserts = len((r.assertion_results or []))
        dur = f"{r.duration_ms}ms" if r.duration_ms else "—"
        items.append({
            "type": "replay", "id": r.id, "title": f"回放 #{r.id}",
            "subtitle": f"{r.status} · {r.mode} · {steps} 步 · {asserts} 断言 · {dur}",
            "ts": r.created_at.isoformat(),
        })

    # 四分类报告
    for r in db.query(DeltaReport).order_by(
            DeltaReport.created_at.desc()).limit(limit).all():
        items.append({
            "type": "report", "id": r.id, "title": f"报告 #{r.id}",
            "subtitle": (f"E{len(r.expected or [])} M{len(r.missing or [])} "
                         f"U{len(r.unexpected or [])} D{len(r.drift or [])}"),
            "ts": r.created_at.isoformat(),
        })

    # 评审
    for r in db.query(Review).order_by(
            Review.created_at.desc()).limit(limit).all():
        items.append({
            "type": "review", "id": r.id, "title": f"评审 #{r.id}",
            "subtitle": f"{r.decision} by {r.reviewer}",
            "ts": r.created_at.isoformat(),
        })

    # LLM 调用（只列摘要，详情走 /audit/llm-logs/{id}）
    for l in db.query(LlmCallLog).order_by(
            LlmCallLog.created_at.desc()).limit(limit).all():
        items.append({
            "type": "llm", "id": l.id, "title": f"LLM {l.purpose}",
            "subtitle": f"{l.provider} · {l.latency_ms}ms · {l.prompt_tokens or '—'}/{l.completion_tokens or '—'} tokens",
            "ts": l.created_at.isoformat(),
        })

    # 夜间运行
    for a in db.query(AgentRun).order_by(
            AgentRun.started_at.desc()).limit(limit).all():
        nodes = len(a.node_outputs or [])
        items.append({
            "type": "agent_run", "id": a.id, "title": f"运行 #{a.id} {a.graph_name}",
            "subtitle": f"{a.status} · {nodes} 节点",
            "ts": a.started_at.isoformat(),
        })

    # 按时间倒序
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]
