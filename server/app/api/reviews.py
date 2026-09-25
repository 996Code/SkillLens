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
from app.models import AgentRun, Review

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
    reviewer: str
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
        "decision": row.decision,
        "comment": row.comment,
        "created_at": row.created_at.isoformat(),
        "agent_run": _run_summary(run) if run else None,
    }


@router.post("/reviews", status_code=201)
async def create_review(body: ReviewIn, db: Session = Depends(get_db)) -> dict:
    run = db.get(AgentRun, body.agent_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="agent_run not found")
    dup = db.query(Review).filter(Review.agent_run_id == body.agent_run_id).first()
    if dup:
        raise HTTPException(status_code=409,
                            detail=f"agent_run {body.agent_run_id} 已评审（review #{dup.id}）")
    row = Review(agent_run_id=body.agent_run_id, reviewer=body.reviewer,
                 decision=body.decision, comment=body.comment)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _review_item(db, row)


@router.get("/reviews")
async def list_reviews(decision: DECISIONS | None = None,
                       db: Session = Depends(get_db)) -> list:
    query = db.query(Review).order_by(Review.id.desc())
    if decision:
        query = query.filter(Review.decision == decision)
    return [_review_item(db, row) for row in query.all()]


@router.get("/reviews/pending")
async def list_pending_runs(db: Session = Depends(get_db)) -> list:
    """未评审的 agent_run 队列（评审门户首页数据源）。

    node_outputs 摘要透传（含 review_output 段若有）；graph_name 前缀
    canvas:/nightly 均含——夜间图与画布运行统一进评审队列。
    """
    reviewed_ids = {rid for (rid,) in db.query(Review.agent_run_id).all()}
    runs = db.query(AgentRun).order_by(AgentRun.id.desc()).all()
    return [{
        "id": r.id,
        "graph_name": r.graph_name,
        "status": r.status,
        "started_at": r.started_at.isoformat(),
        "node_outputs": r.node_outputs or [],
    } for r in runs if r.id not in reviewed_ids]
