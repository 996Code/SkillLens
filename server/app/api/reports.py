"""四分类报告只读端点（S9 块C Task 4）：工作台报告页（C2）的数据源。

报告行只由 POST /expected-deltas/{id}/report 写入；GET /reports/{id} 纯读取
四分类数组 + 关联 id + 时间戳，不做任何计算（只读边界）。
S23 块 V：GET /reports/{id}/perf 为只读派生端点——从 replay_run 重算性能
上下文（基线/当前/历史），不写库。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.change.perf import perf_context
from app.db import SessionLocal
from app.models import DeltaReport, ObservedDelta

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/reports/{report_id}")
async def get_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(DeltaReport, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    return {"id": row.id,
            "expected_delta_id": row.expected_delta_id,
            "observed_delta_id": row.observed_delta_id,
            "expected": row.expected, "missing": row.missing,
            "unexpected": row.unexpected, "drift": row.drift,
            "created_at": row.created_at.isoformat()}


@router.get("/reports/{report_id}/perf")
async def get_report_perf(report_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(DeltaReport, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    obs = db.get(ObservedDelta, row.observed_delta_id)
    if not obs:
        raise HTTPException(404, "observed delta not found")
    perf_ctx, _ = perf_context(db, obs.skill_id, obs.replay_run_id)
    return perf_ctx
