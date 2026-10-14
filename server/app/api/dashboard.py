"""S28 块 Y：仪表盘聚合端点——工作台首页一次请求全量概览。

GET /api/v1/dashboard →
- skills：{total, learned, candidate, generic_learned}
- replays：{total, pass, fail, error, shadow, flaky, recent: 最近 10 条（含 skill 名）}
- reports：{total, last: 最近一条四分类计数}
- trend：最近 14 天每日回放 {date, total, pass}（趋势图数据）
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (AgentRun, DeltaReport, GenericSkill,
                        ReplayRun, Review, Skill)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


@router.get("/dashboard")
async def get_dashboard(db: Session = Depends(get_db)) -> dict:
    skills_total = db.query(func.count(Skill.id)).filter(
        Skill.status != "superseded").scalar() or 0
    skills_learned = db.query(func.count(Skill.id)).filter(
        Skill.status == "learned").scalar() or 0
    skills_candidate = db.query(func.count(Skill.id)).filter(
        Skill.status == "candidate").scalar() or 0
    generic_learned = db.query(func.count(GenericSkill.id)).filter(
        GenericSkill.status == "learned").scalar() or 0

    # S42：GROUP BY 聚合替代全量加载（ReplayRun 行含巨型 JSON 列，
    # 整表载入仅为计数在回放次数多时拖垮首页）
    status_rows = db.query(ReplayRun.status, func.count(ReplayRun.id)).group_by(
        ReplayRun.status).all()
    by_status: dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "shadow": 0}
    total = 0
    for status, n in status_rows:
        total += n
        if status in by_status:
            by_status[status] = n
    flaky = db.query(func.count(ReplayRun.id)).filter(
        ReplayRun.flaky == True).scalar() or 0  # noqa: E712

    # UI 优化批1（性能）：列选择——plan 列不加载
    recent_rows = db.query(
        ReplayRun.id, ReplayRun.skill_id, ReplayRun.status, ReplayRun.mode,
        ReplayRun.flaky, ReplayRun.duration_ms, ReplayRun.created_at,
    ).order_by(ReplayRun.id.desc()).limit(10).all()
    skill_names = {s.id: s.name for s in db.query(Skill.id, Skill.name).filter(
        Skill.id.in_([r.skill_id for r in recent_rows] or [0])).all()}
    recent = [{
        "id": r.id, "skill_id": r.skill_id,
        "skill_name": skill_names.get(r.skill_id, f"#{r.skill_id}"),
        "status": r.status, "mode": r.mode, "flaky": bool(r.flaky),
        "duration_ms": r.duration_ms, "ts": r.created_at.isoformat(),
    } for r in recent_rows]

    # 趋势：最近 14 天每日回放计数（含 pass）——SQL 按日聚合
    days: dict[str, dict] = {}
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        days[_day_key(d)] = {"date": _day_key(d), "total": 0, "pass": 0}
    since = (today - timedelta(days=13)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    trend_rows = db.query(
        func.date(ReplayRun.created_at), ReplayRun.status, func.count(ReplayRun.id)
    ).filter(ReplayRun.created_at >= since).group_by(
        func.date(ReplayRun.created_at), ReplayRun.status).all()
    for d, status, n in trend_rows:
        k = str(d)
        if k in days:
            days[k]["total"] += n
            if status == "pass":
                days[k]["pass"] += n

    reports_total = db.query(func.count(DeltaReport.id)).scalar() or 0
    last_report = db.query(DeltaReport).order_by(DeltaReport.id.desc()).first()
    reports_last = None
    if last_report:
        reports_last = {
            "id": last_report.id,
            "expected": len(last_report.expected or []),
            "missing": len(last_report.missing or []),
            "unexpected": len(last_report.unexpected or []),
            "drift": len(last_report.drift or []),
            "created_at": last_report.created_at.isoformat(),
        }

    # S42：待评审数 = 未评审的 agent_run（此前误统计全部 Review 行，
    # 字段名与语义不符）
    reviewed_ids = {rid for (rid,) in db.query(Review.agent_run_id).all()}
    reviews_pending = db.query(AgentRun).filter(
        ~AgentRun.id.in_(reviewed_ids or [0])).count()

    return {
        "skills": {"total": skills_total, "learned": skills_learned,
                   "candidate": skills_candidate,
                   "generic_learned": generic_learned},
        "replays": {"total": total, **by_status, "flaky": flaky,
                    "recent": recent},
        "reports": {"total": reports_total, "last": reports_last},
        "reviews_pending": reviews_pending,
        "trend": list(days.values()),
    }
