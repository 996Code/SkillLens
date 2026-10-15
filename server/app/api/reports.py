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


# ---------- AR4：场景报告（ScenarioRun 终态自动生成） ----------

from app.models import ReportDelta, ReportReview, ScenarioReport, ScenarioRun
from pydantic import BaseModel, Field
from typing import Literal
from app.api.auth import require_role
from fastapi import Depends as _Depends, Header as _Header


def _srep_summary(row: ScenarioReport) -> dict:
    run = None
    from app.db import SessionLocal
    s = SessionLocal()
    try:
        run = s.get(ScenarioRun, row.scenario_run_id)
    finally:
        s.close()
    return {
        "id": row.id,
        "scenario_run_id": row.scenario_run_id,
        "scenario_id": run.scenario_id if run else None,
        "status": row.status,
        "coverage_state": row.coverage_state,
        "source_track": row.source_track,
        "expected_count": row.expected_count,
        "missing_count": row.missing_count,
        "unexpected_count": row.unexpected_count,
        "drift_count": row.drift_count,
        "attempt_count": row.attempt_count,
        "error_code": row.error_code,
        "error_summary": row.error_summary,
        "created_at": row.created_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


@router.get("/scenario-runs/{run_id}/report")
async def get_run_report(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ScenarioRun, run_id)
    if not run:
        raise HTTPException(404, "scenario_run not found")
    row = db.query(ScenarioReport).filter(
        ScenarioReport.scenario_run_id == run_id).first()
    if not row:
        raise HTTPException(404, "报告尚未生成")
    out = _srep_summary(row)
    out["deltas"] = [{
        "expectation_key": d.expectation_key,
        "expected_delta_id": d.expected_delta_id,
        "expected": d.expected, "missing": d.missing,
        "unexpected": d.unexpected, "drift": d.drift,
        "evidence_replay_run_ids": d.evidence_replay_run_ids,
    } for d in db.query(ReportDelta).filter(
        ReportDelta.scenario_report_id == row.id).all()]
    return out


@router.get("/scenario-reports")
async def list_scenario_reports(status: str = "", coverage: str = "",
                                limit: int = 50,
                                db: Session = Depends(get_db)) -> list[dict]:
    """AR4 场景报告列表（轻量列）。"""
    q = db.query(ScenarioReport)
    if status:
        q = q.filter(ScenarioReport.status == status)
    if coverage:
        q = q.filter(ScenarioReport.coverage_state == coverage)
    rows = q.order_by(ScenarioReport.id.desc()).limit(limit).all()
    reviewed = {r[0] for r in db.query(ReportReview.report_id).all()}
    out = []
    for r in rows:
        item = _srep_summary(r)
        item["review_state"] = "reviewed" if r.id in reviewed else "pending"
        out.append(item)
    return out


@router.post("/scenario-reports/{report_id}/retry",
             dependencies=[_Depends(require_role("reviewer", "admin"))])
async def retry_report(report_id: int, db: Session = Depends(get_db)) -> dict:
    """仅 generation_failed 可重试（幂等 upsert 同一报告）。"""
    row = db.get(ScenarioReport, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    if row.status != "generation_failed":
        raise HTTPException(409, f"仅 generation_failed 可重试（当前 {row.status}）")
    from app.reports.service import generate_report
    run = db.get(ScenarioRun, row.scenario_run_id)
    row.attempt_count += 1
    db.commit()
    return _srep_summary(generate_report(db, run))


class ReviewIn(BaseModel):
    decision: Literal["approved", "rejected", "changes_requested"]
    comment: str | None = None


@router.post("/reports/{report_id}/review", status_code=201,
             dependencies=[_Depends(require_role("reviewer", "admin"))])
async def review_report(report_id: int, body: ReviewIn,
                        db: Session = Depends(get_db),
                        user=_Depends(require_role("reviewer", "admin"))) -> dict:
    """AR4 报告评审：一报告一评审，决策不可变。"""
    row = db.get(ScenarioReport, report_id)
    if not row:
        raise HTTPException(404, "report not found")
    if row.status != "ready":
        raise HTTPException(409, f"报告未就绪（{row.status}）")
    dup = db.query(ReportReview).filter(
        ReportReview.report_id == report_id).first()
    if dup:
        raise HTTPException(409, f"报告已评审（review #{dup.id}）")
    review = ReportReview(report_id=report_id, reviewer=user.username,
                          user_id=user.id, decision=body.decision,
                          comment=body.comment)
    db.add(review)
    db.commit()
    db.refresh(review)
    return {"id": review.id, "report_id": report_id,
            "reviewer": review.reviewer, "decision": review.decision,
            "comment": review.comment,
            "created_at": review.created_at.isoformat()}
