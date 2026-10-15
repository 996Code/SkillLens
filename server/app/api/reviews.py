"""S15 I1 评审门户后端：夜间 agent_run 的 PR 式评审流。

- POST /api/v1/reviews {agent_run_id, reviewer, decision, comment?}：
  decision 三选一 approved|rejected|changes_requested（Literal 422）；
  agent_run 不存在 404；同 run 已评审 409；201 返回评审行（含 agent_run 摘要）。
- GET /api/v1/reviews?decision=：评审列表（id 倒序），每项含 agent_run 摘要
  （graph_name/status/started_at）。
- GET /api/v1/reviews/pending：未评审的 agent_run 队列（id 倒序），
  node_outputs 摘要透传——评审页据此渲染 review_output 段（若有）。

与四分类报告页（/reports/:deltaId）区分：本模块评审的是夜间运行（agent_run），
报告页看的是发版四分类。C3：评审决策落库可审计。
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AgentRun, Review, User
from app.api.auth import require_role

router = APIRouter()

DECISIONS = Literal["approved", "rejected", "changes_requested"]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ReviewIn(BaseModel):
    agent_run_id: int
    decision: DECISIONS
    comment: str | None = None


def _run_summary(run: AgentRun) -> dict:
    return {"graph_name": run.graph_name, "status": run.status,
            "started_at": run.started_at.isoformat()}


def _review_item(db: Session, row: Review) -> dict:
    run = db.get(AgentRun, row.agent_run_id)
    return {
        "id": row.id,
        "agent_run_id": row.agent_run_id,
        "reviewer": row.reviewer,
        "user_id": row.user_id,
        "decision": row.decision,
        "comment": row.comment,
        "created_at": row.created_at.isoformat(),
        "agent_run": _run_summary(run) if run else None,
    }


@router.post("/reviews", status_code=201)
async def create_review(body: ReviewIn, db: Session = Depends(get_db),
                        user: User = Depends(require_role("reviewer", "admin"))) -> dict:
    raise HTTPException(
        status_code=410,
        detail="旧 AgentRun 评审写入已由 AR1 冻结；AR4 将评审对象统一为场景报告",
    )


@router.get("/reviews")
async def list_reviews(decision: DECISIONS | None = None,
                       db: Session = Depends(get_db)) -> list:
    query = db.query(Review).order_by(Review.id.desc())
    if decision:
        query = query.filter(Review.decision == decision)
    return [_review_item(db, row) for row in query.all()]


@router.get("/reviews/pending")
async def list_pending_runs(db: Session = Depends(get_db)) -> list:
    """AR4：待评审队列 = ready 且未评审的场景报告（新主链）。

    旧 AgentRun 队列已冻结（AR1 写冻结+AR4 评审对象切换）。
    """
    from app.models import ReportReview, ScenarioReport, ScenarioRun
    reviewed = {rid for (rid,) in db.query(ReportReview.report_id).all()}
    rows = db.query(ScenarioReport).filter(
        ScenarioReport.status == "ready"
    ).order_by(ScenarioReport.id.desc()).limit(100).all()
    out = []
    for r in rows:
        if r.id in reviewed:
            continue
        run = db.get(ScenarioRun, r.scenario_run_id)
        out.append({
            "report_id": r.id,
            "scenario_run_id": r.scenario_run_id,
            "scenario_id": run.scenario_id if run else None,
            "coverage_state": r.coverage_state,
            "missing_count": r.missing_count,
            "unexpected_count": r.unexpected_count,
            "drift_count": r.drift_count,
            "created_at": r.created_at.isoformat(),
        })
    return out
