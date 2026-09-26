"""S19 T1/T2：流程生成（synth_flow）端点。

POST /flows/generate        生成（证据收集 + LLM 目标分解 + 确定性回查 → proposed）
GET  /flows                 列表（倒序）
GET  /flows/{id}            详情
POST /flows/{id}/execute    执行（C1：写锚点需 confirm；T2）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.learning.synthesis import synth_flow
from app.models import SynthFlow

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class FlowGenerateRequest(BaseModel):
    goal: str = Field(min_length=1)
    system_hint: str = Field(min_length=1, max_length=200)


@router.post("/flows/generate", status_code=201)
async def generate_flow(body: FlowGenerateRequest,
                        db: Session = Depends(get_db)) -> dict:
    row = synth_flow(db, body.goal, body.system_hint)
    return {"id": row.id, "goal": row.goal, "system_hint": row.system_hint,
            "status": row.status, "steps": row.steps, "notes": row.notes,
            "evidence_refs": row.evidence_refs}


@router.get("/flows")
async def list_flows(db: Session = Depends(get_db)) -> list:
    rows = db.query(SynthFlow).order_by(SynthFlow.id.desc()).all()
    return [{"id": r.id, "goal": r.goal, "status": r.status,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.get("/flows/{flow_id}")
async def get_flow(flow_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(SynthFlow, flow_id)
    if not row:
        raise HTTPException(404, "flow not found")
    return {"id": row.id, "goal": row.goal, "system_hint": row.system_hint,
            "status": row.status, "steps": row.steps, "notes": row.notes,
            "evidence_refs": row.evidence_refs,
            "execution_log": row.execution_log,
            "created_at": row.created_at.isoformat() if row.created_at else None}


class FlowExecuteRequest(BaseModel):
    confirm_side_effect: bool = False


@router.post("/flows/{flow_id}/execute")
async def execute_flow(flow_id: int, body: FlowExecuteRequest,
                       db: Session = Depends(get_db)) -> dict:
    """执行生成流程。C1：步骤 click 锚点关联写 API（POST/PUT/DELETE）→
    confirm_side_effect=false 则 409 不启浏览器（与回放 shadow 门控同纪律）。
    执行复用回放通道浏览器入口，全程落 execution_log（C3）；成功不自动
    induce（v1），notes 记自学习提示。"""
    from app.replay.flow_runner import execute_flow as run_flow
    from app.replay.flow_runner import flow_requires_confirmation
    row = db.get(SynthFlow, flow_id)
    if not row:
        raise HTTPException(404, "flow not found")
    if flow_requires_confirmation(db, row.steps) and not body.confirm_side_effect:
        raise HTTPException(409, "生成流程含写操作，需确认")
    row = await run_flow(db, row)
    return {"id": row.id, "status": row.status, "notes": row.notes,
            "execution_log": row.execution_log}
