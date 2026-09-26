"""S18 T1/T2：夜间开发计划端点。

POST /dev-plans                生成（LLM 结构化 + 确定性回查 → draft）
GET  /dev-plans                列表（倒序）
GET  /dev-plans/{id}           详情
POST /dev-plans/{id}/confirm   人工确认（C1 延伸门控：draft → confirmed）
POST /dev-plans/{id}/execute   执行（仅 confirmed 可执行；执行器 T3 实现）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.learning.devplan import generate_dev_plan
from app.models import DevPlan

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class DevPlanCreateRequest(BaseModel):
    requirement_text: str = Field(min_length=1)
    target_form: str = Field(min_length=1, max_length=100)


@router.post("/dev-plans", status_code=201)
async def create_dev_plan(body: DevPlanCreateRequest,
                          db: Session = Depends(get_db)) -> dict:
    row = generate_dev_plan(db, body.requirement_text, body.target_form)
    return {"id": row.id, "status": row.status, "target_form": row.target_form,
            "changes": row.changes, "notes": row.notes}


@router.get("/dev-plans")
async def list_dev_plans(db: Session = Depends(get_db)) -> list:
    rows = db.query(DevPlan).order_by(DevPlan.id.desc()).all()
    return [{"id": r.id, "target_form": r.target_form, "status": r.status,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.get("/dev-plans/{plan_id}")
async def get_dev_plan(plan_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(DevPlan, plan_id)
    if not row:
        raise HTTPException(404, "dev plan not found")
    return {"id": row.id, "requirement_text": row.requirement_text,
            "target_form": row.target_form, "changes": row.changes,
            "status": row.status, "execution_log": row.execution_log,
            "reviewed_by": row.reviewed_by, "notes": row.notes,
            "created_at": row.created_at.isoformat() if row.created_at else None}


class ConfirmRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=100)


@router.post("/dev-plans/{plan_id}/confirm")
async def confirm_dev_plan(plan_id: int, body: ConfirmRequest,
                           db: Session = Depends(get_db)) -> dict:
    """C1 延伸门控：draft → confirmed（人工确认，同 expected-delta 模式）。"""
    row = db.get(DevPlan, plan_id)
    if not row:
        raise HTTPException(404, "dev plan not found")
    if row.status == "confirmed":
        raise HTTPException(409, "已确认过，不可重复确认")
    row.status = "confirmed"
    row.reviewed_by = body.reviewed_by
    db.commit()
    db.refresh(row)
    return {"id": row.id, "status": row.status, "reviewed_by": row.reviewed_by}


@router.post("/dev-plans/{plan_id}/execute")
async def execute_dev_plan(plan_id: int, db: Session = Depends(get_db)) -> dict:
    """仅 confirmed 可执行（C1 延伸：draft 计划不可执行）。
    执行走浏览器自动化（常驻窗口可见），全程落 execution_log（C3）。"""
    row = db.get(DevPlan, plan_id)
    if not row:
        raise HTTPException(404, "dev plan not found")
    if row.status != "confirmed":
        raise HTTPException(409, "计划未确认，不可执行")
    from app.agents.dev_executor import execute_dev_plan as run_executor
    row = await run_executor(db, row)
    return {"id": row.id, "status": row.status,
            "execution_log": row.execution_log}
