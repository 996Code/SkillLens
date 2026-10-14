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


@router.get("/reports")
async def list_reports(db: Session = Depends(get_db)) -> list[dict]:
    """UI 优化批1：报告列表——行轻量化（json_array_length SQL 端计数，
    不加载 expected/missing/unexpected/drift 大 JSON），created_at 倒序。"""
    from sqlalchemy import func as _f
    rows = db.query(
        DeltaReport.id, DeltaReport.expected_delta_id,
        DeltaReport.observed_delta_id, DeltaReport.created_at,
        _f.ifnull(_f.json_array_length(DeltaReport.expected), 0),
        _f.ifnull(_f.json_array_length(DeltaReport.missing), 0),
        _f.ifnull(_f.json_array_length(DeltaReport.unexpected), 0),
        _f.ifnull(_f.json_array_length(DeltaReport.drift), 0),
    ).order_by(DeltaReport.created_at.desc()).all()
    return [{"id": r[0], "expected_delta_id": r[1],
             "observed_delta_id": r[2], "created_at": r[3].isoformat(),
             "expected_count": r[4], "missing_count": r[5],
             "unexpected_count": r[6], "drift_count": r[7]} for r in rows]


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
