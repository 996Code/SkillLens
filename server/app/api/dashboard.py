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
from app.models import (DeltaReport, GenericSkill, ReplayRun, Review, Skill)

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

    runs = db.query(ReplayRun).order_by(ReplayRun.id.desc()).all()
    by_status: dict[str, int] = {"pass": 0, "fail": 0, "error": 0, "shadow": 0}
    flaky = 0
    for r in runs:
        if r.status in by_status:
            by_status[r.status] += 1
        if r.flaky:
            flaky += 1

    skill_names = {s.id: s.name for s in db.query(Skill.id, Skill.name).all()}
    recent = [{
        "id": r.id, "skill_id": r.skill_id,
        "skill_name": skill_names.get(r.skill_id, f"#{r.skill_id}"),
        "status": r.status, "mode": r.mode, "flaky": bool(r.flaky),
        "duration_ms": r.duration_ms, "ts": r.created_at.isoformat(),
    } for r in runs[:10]]

    # 趋势：最近 14 天每日回放计数（含 pass）
    days: dict[str, dict] = {}
    today = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        days[_day_key(d)] = {"date": _day_key(d), "total": 0, "pass": 0}
    for r in runs:
        k = _day_key(r.created_at.replace(tzinfo=None))
        if k in days:
            days[k]["total"] += 1
            if r.status == "pass":
                days[k]["pass"] += 1

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

    reviews_pending = db.query(Review).count()

    return {
        "skills": {"total": skills_total, "learned": skills_learned,
                   "candidate": skills_candidate,
                   "generic_learned": generic_learned},
        "replays": {"total": len(runs), **by_status, "flaky": flaky,
                    "recent": recent},
        "reports": {"total": reports_total, "last": reports_last},
        "reviews_pending": reviews_pending,
        "trend": list(days.values()),
    }
