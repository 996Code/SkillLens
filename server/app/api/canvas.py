"""S14 H2：编排画布端点。

POST /canvas            保存画布（validate 通过才存；版本化=每次保存新行）
GET  /canvas            列表（id/name/created_at，倒序）
GET  /canvas/{id}       详情（含 dag）
POST /canvas/{id}/run   编译执行（run_canvas_graph 通道，落 agent_run）
GET  /canvas/{id}/runs  该画布的 agent_run 列表（graph_name 前缀过滤）
GET  /canvas/runs/{agent_run_id}  agent_run 详情（Task 3 前端着色/产物下钻）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.canvas import compile_and_run, validate_dag
from app.db import SessionLocal
from app.models import AgentRun, CanvasDag

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CanvasCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    dag: dict


@router.post("/canvas", status_code=201)
async def create_canvas(body: CanvasCreateRequest,
                        db: Session = Depends(get_db)) -> dict:
    ok, errors = validate_dag(body.dag)
    if not ok:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    row = CanvasDag(name=body.name, dag=body.dag)  # 版本化：新行不覆盖
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id}


@router.get("/canvas")
async def list_canvas(db: Session = Depends(get_db)) -> list:
    rows = db.query(CanvasDag).order_by(CanvasDag.id.desc()).all()
    return [{"id": r.id, "name": r.name,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]


@router.get("/canvas/{canvas_id}")
async def get_canvas(canvas_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CanvasDag, canvas_id)
    if not row:
        raise HTTPException(status_code=404, detail="canvas not found")
    return {"id": row.id, "name": row.name, "dag": row.dag,
            "created_at": row.created_at.isoformat() if row.created_at else None}


@router.post("/canvas/{canvas_id}/run")
async def run_canvas(canvas_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(CanvasDag, canvas_id)
    if not row:
        raise HTTPException(status_code=404, detail="canvas not found")
    run = await compile_and_run(db, row)
    return {"id": run.id, "canvas_id": canvas_id, "status": run.status,
            "graph_name": run.graph_name, "node_outputs": run.node_outputs,
            "error_text": run.error_text}


@router.get("/canvas/runs/{agent_run_id}")
async def get_canvas_run(agent_run_id: int,
                         db: Session = Depends(get_db)) -> dict:
    """S14 Task 3：agent_run 详情轻端点（前端节点着色/产物下钻用）。
    只暴露 canvas 图的 run（graph_name 前缀隔离，不泄露其他图）。"""
    run = (db.query(AgentRun)
           .filter(AgentRun.id == agent_run_id,
                   AgentRun.graph_name.like("canvas:%")).first())
    if not run:
        raise HTTPException(status_code=404, detail="agent run not found")
    return {"id": run.id, "status": run.status, "node_outputs": run.node_outputs,
            "input": run.input, "error_text": run.error_text}


@router.get("/canvas/{canvas_id}/runs")
async def list_canvas_runs(canvas_id: int,
                           db: Session = Depends(get_db)) -> list:
    row = db.get(CanvasDag, canvas_id)
    if not row:
        raise HTTPException(status_code=404, detail="canvas not found")
    runs = (db.query(AgentRun)
            .filter(AgentRun.graph_name == f"canvas:{canvas_id}")
            .order_by(AgentRun.id.desc()).all())
    return [{"id": r.id, "status": r.status,
             "started_at": r.started_at.isoformat() if r.started_at else None,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None,
             "node_count": len(r.node_outputs or [])} for r in runs]
