"""S13 F2：Impact Analysis 端点。

POST /impact/analyze {api_templates?, anchor_labels?}（至少一项，422）
GET  /impact/last（最近一次 graph_name=nightly 的 agent_run 输入输出）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.learning.impact import analyze_impact
from app.models import AgentRun

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ImpactRequest(BaseModel):
    api_templates: list[str] = []
    anchor_labels: list[str] = []

    @model_validator(mode="after")
    def _require_at_least_one(self):
        if not self.api_templates and not self.anchor_labels:
            raise ValueError("api_templates 与 anchor_labels 至少提供一项")
        return self


@router.post("/impact/analyze")
async def analyze(body: ImpactRequest, db: Session = Depends(get_db)) -> dict:
    return analyze_impact(db, body.api_templates, body.anchor_labels)


@router.get("/impact/last")
async def last_nightly_run(db: Session = Depends(get_db)) -> dict:
    run = (db.query(AgentRun).filter(AgentRun.graph_name == "nightly")
           .order_by(AgentRun.id.desc()).first())
    if not run:
        raise HTTPException(status_code=404, detail="no nightly agent run")
    return {"id": run.id, "graph_name": run.graph_name, "input": run.input,
            "node_outputs": run.node_outputs, "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "error_text": run.error_text}
