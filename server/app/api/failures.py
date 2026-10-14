"""失败分析工作台（UI 批2）：failure_class 聚合+下钻。

AJ1 分类学（E1-E4）数据早已落列，此前无任何聚合 UI——"数据在库里、
洞察不可见"。口径与 pass_rate 同源（E1/E2 透明可见不进分母）。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReplayRun, Skill
from app.system import skill_systems

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_CLASS_LABELS = {
    "e1_env": "环境失败（不进分母）",
    "e2_infra": "基础设施（不进分母）",
    "e3_drift": "漂移（UI/接口变化）",
    "e4_assert": "断言失败（行为偏离）",
}


@router.get("/failures/summary")
async def failures_summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict:
    """近 N 天 fail/error run 按 failure_class 聚合；每类带最近 run
    轻量行（列选择——plan 列不加载，UI 批1 性能纪律）。"""
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.query(
        ReplayRun.id, ReplayRun.skill_id, ReplayRun.status,
        ReplayRun.failure_class, ReplayRun.created_at,
    ).filter(
        ReplayRun.created_at >= since,
        ReplayRun.status.in_(("fail", "error")),
    ).order_by(ReplayRun.created_at.desc()).all()

    names = {sid: name for sid, name in db.query(Skill.id, Skill.name).filter(
        Skill.id.in_({r.skill_id for r in rows} or {0}))}
    systems = skill_systems(db, [r.skill_id for r in rows])

    by_class: dict[str, dict] = {}
    unclassified = 0
    for r in rows:
        cls = r.failure_class or "unclassified"
        agg = by_class.setdefault(cls, {"count": 0, "runs": [],
                                        "label": _CLASS_LABELS.get(cls, cls)})
        agg["count"] += 1
        if len(agg["runs"]) < 20:
            agg["runs"].append({
                "id": r.id, "skill_id": r.skill_id,
                "skill_name": names.get(r.skill_id, f"#{r.skill_id}"),
                "status": r.status, "failure_class": r.failure_class,
                "system": systems.get(r.skill_id, "未知系统"),
                "created_at": r.created_at.isoformat()})
        if not r.failure_class:
            unclassified += 1

    return {"total": len(rows), "unclassified": unclassified,
            "by_class": dict(sorted(by_class.items(),
                                    key=lambda kv: -kv[1]["count"]))}
