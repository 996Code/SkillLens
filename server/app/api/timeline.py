"""S32 链路时间线 → S37-2 重构为测试活动视角。

GET /api/v1/timeline → 按时间倒序的**测试活动**列表（用户视角）：
- test_run: 自动测试运行（回放）——skill 名/状态/模式/耗时
- recording: 录制学习会话——学到哪些操作流程、事件数

内部事件（llm/alignment/session 处理/agent_run/report/review）默认不出现在
主行（对使用者是噪音）；include_internal=true 时附带（开发者视角）。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (AgentRun, Alignment, DeltaReport, LlmCallLog,
                        RawEvent, RecordingSession, ReplayRun, Review, Skill)
from app.system import session_system, skill_systems

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _session_skills(db: Session) -> dict[str, list[dict]]:
    """session_id -> 该会话学习产出的操作流程清单。"""
    out: dict[str, list[dict]] = {}
    alignments = db.query(Alignment.id, Alignment.session_ids).all()
    aid_to_sids = {a.id: (a.session_ids or []) for a in alignments}
    for s in db.query(Skill.id, Skill.name, Skill.alignment_id).all():
        for sid in aid_to_sids.get(s.alignment_id, []):
            out.setdefault(sid, []).append({"id": s.id, "name": s.name})
    return out


@router.get("/timeline")
async def get_timeline(
    limit: int = Query(50, ge=1, le=200),
    include_internal: bool = Query(False),
    db: Session = Depends(get_db),
) -> list:
    items: list[dict] = []
    systems = skill_systems(db)  # S38：目标系统维度

    # 测试运行（自动测试）
    for r in db.query(ReplayRun).order_by(
            ReplayRun.created_at.desc()).limit(limit).all():
        skill = db.get(Skill, r.skill_id)
        skill_name = skill.name if skill else f"#{r.skill_id}"
        steps = len((r.executed or []))
        dur = f"{r.duration_ms}ms" if r.duration_ms else "—"
        system = systems.get(r.skill_id, "未知系统")
        items.append({
            "type": "test_run", "id": r.id,
            "title": f"自动测试 · {skill_name}",
            "subtitle": f"{system} · {r.status} · {r.mode} · {steps} 步 · {dur}",
            "ts": r.created_at.isoformat(),
            "system": system,
        })

    # 录制学习会话（含学习产出清单）
    skills_by_session = _session_skills(db)
    for s in db.query(RecordingSession).order_by(
            RecordingSession.started_at.desc()).limit(limit).all():
        ev = db.query(RawEvent.id).filter(
            RawEvent.session_id == s.id).count()
        learned = skills_by_session.get(s.id, [])
        sub = f"事件 {ev}"
        if learned:
            sub += f" · 学到 {len(learned)} 个操作流程"
        if s.note:
            sub += f" · {s.note}"
        system = session_system(db, s.id)
        items.append({
            "type": "recording", "id": s.id,
            "title": f"录制学习 · {(s.note or s.id[:8])}",
            "subtitle": f"{system} · {sub}",
            "ts": s.started_at.isoformat(),
            "skills": learned,
            "system": system,
        })

    if include_internal:
        # 内部事件（开发者视角）：LLM 调用 / 夜间运行 / 报告 / 评审
        for l in db.query(LlmCallLog).order_by(
                LlmCallLog.created_at.desc()).limit(limit).all():
            items.append({
                "type": "llm", "id": l.id, "title": f"LLM {l.purpose}",
                "subtitle": (f"{l.provider} · {l.latency_ms}ms · "
                             f"{l.prompt_tokens or '—'}/{l.completion_tokens or '—'} tokens"),
                "ts": l.created_at.isoformat(),
            })
        for a in db.query(AgentRun).order_by(
                AgentRun.started_at.desc()).limit(limit).all():
            nodes = len(a.node_outputs or [])
            items.append({
                "type": "agent_run", "id": a.id,
                "title": f"运行 #{a.id} {a.graph_name}",
                "subtitle": f"{a.status} · {nodes} 节点",
                "ts": a.started_at.isoformat(),
            })
        for r in db.query(DeltaReport).order_by(
                DeltaReport.created_at.desc()).limit(limit).all():
            items.append({
                "type": "report", "id": r.id, "title": f"报告 #{r.id}",
                "subtitle": (f"E{len(r.expected or [])} M{len(r.missing or [])} "
                             f"U{len(r.unexpected or [])} D{len(r.drift or [])}"),
                "ts": r.created_at.isoformat(),
            })
        for r in db.query(Review).order_by(
                Review.created_at.desc()).limit(limit).all():
            items.append({
                "type": "review", "id": r.id, "title": f"评审 #{r.id}",
                "subtitle": f"{r.decision} by {r.reviewer}",
                "ts": r.created_at.isoformat(),
            })

    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]
