"""S37-3 测试套件 → S38 与流水线合并：套件 = 自动生成的线性流水线。

- POST /suites          创建（name + skill_ids）→ 同步生成线性 canvas_dag
                        （skill_source → replay_batch → aggregate），
                        套件与画布同一对象两个视图
- GET /suites           列表（含 skill 概要 + canvas_id + 目标系统）
- GET /suites/{id}      详情
- DELETE /suites/{id}   删除
- POST /suites/{id}/run 一键执行 = 画布运行（compile_and_run → agent_run，
                        node_outputs 留全量产物）；confirm 与定格值不同时
                        生成新版本 canvas_dag（C1 编译期定格 + 版本化）
- GET /suites/{id}/runs 执行历史（含 agent_run_id 可下钻节点产物）
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.canvas import compile_and_run
from app.db import SessionLocal
from app.models import AgentRun, CanvasDag, Skill, SuiteRun, TestSuite
from app.system import skill_systems

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SuiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    skill_ids: list[int] = Field(min_length=1)


class SuiteRunIn(BaseModel):
    confirm_side_effect: bool = False


def _suite_dag(skill_ids: list[int], confirm: bool) -> dict:
    """套件的线性流水线：固定技能清单 → 批量自动测试 → 汇总。"""
    return {
        "nodes": [
            {"id": "n1", "type": "skill_source",
             "params": {"skill_ids": skill_ids}, "x": 80, "y": 160},
            {"id": "n2", "type": "replay_batch",
             "params": {"confirm_side_effect": confirm}, "x": 360, "y": 160},
            {"id": "n3", "type": "aggregate", "params": {}, "x": 640, "y": 160},
        ],
        "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
    }


def _dag_confirm(dag: dict) -> bool:
    for n in (dag or {}).get("nodes") or []:
        if n.get("type") == "replay_batch":
            return bool((n.get("params") or {}).get("confirm_side_effect", False))
    return False


def _suite_item(db: Session, s: TestSuite) -> dict:
    skills = [db.get(Skill, sid) for sid in (s.skill_ids or [])]
    systems = skill_systems(db)
    return {
        "id": s.id, "name": s.name,
        "skill_ids": s.skill_ids or [],
        "skills": [{"id": sk.id, "name": sk.name, "status": sk.status,
                    "system": systems.get(sk.id, "未知系统")}
                   for sk in skills if sk is not None],
        "canvas_id": s.canvas_id,
        "created_at": s.created_at.isoformat(),
    }


def _summary_from_agent_run(db: Session, run: AgentRun) -> dict:
    """从 agent_run.node_outputs 派生套件汇总（replay_results + aggregate）。"""
    results = []
    counts = {}
    for no in (run.node_outputs or []):
        out = no.get("output") or {}
        if "replay_results" in out:
            for r in out["replay_results"]:
                skill = db.get(Skill, r.get("skill_id"))
                results.append({
                    "skill_id": r.get("skill_id"),
                    "skill_name": skill.name if skill else f"#{r.get('skill_id')}",
                    "run_id": r.get("run_id"),
                    "status": r.get("status"),
                    "mode": "shadow" if r.get("status") == "shadow" else "execute",
                })
        if "aggregate" in out:
            counts = out["aggregate"]
    return {"results": results, "counts": counts}


@router.post("/suites")
async def create_suite(body: SuiteIn, db: Session = Depends(get_db)) -> dict:
    for sid in body.skill_ids:
        if db.get(Skill, sid) is None:
            raise HTTPException(status_code=422, detail=f"skill {sid} 不存在")
    # S38 合并：套件 = 线性流水线（预演定格，C1 编译期语义）
    canvas = CanvasDag(name=f"套件 · {body.name}", dag=_suite_dag(body.skill_ids, False))
    db.add(canvas)
    db.commit()
    db.refresh(canvas)
    row = TestSuite(name=body.name, skill_ids=body.skill_ids, canvas_id=canvas.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _suite_item(db, row)


@router.get("/suites")
async def list_suites(db: Session = Depends(get_db)) -> list:
    rows = db.query(TestSuite).order_by(TestSuite.id.desc()).all()
    return [_suite_item(db, r) for r in rows]


@router.get("/suites/{suite_id}")
async def get_suite(suite_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="suite not found")
    return _suite_item(db, row)


@router.delete("/suites/{suite_id}")
async def delete_suite(suite_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(TestSuite, suite_id)
    if not row:
        raise HTTPException(status_code=404, detail="suite not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/suites/{suite_id}/run")
async def run_suite(suite_id: int, body: SuiteRunIn,
                    db: Session = Depends(get_db)) -> dict:
    suite = db.get(TestSuite, suite_id)
    if not suite:
        raise HTTPException(status_code=404, detail="suite not found")
    if not (suite.skill_ids or []):
        raise HTTPException(status_code=422, detail="套件为空")
    canvas = db.get(CanvasDag, suite.canvas_id) if suite.canvas_id else None
    if canvas is None:
        raise HTTPException(status_code=409, detail="套件流水线缺失，请重建套件")
    # C1：confirm 与定格值不同 → 版本化新 canvas_dag（编译期定格语义保持）
    if _dag_confirm(canvas.dag) != body.confirm_side_effect:
        canvas = CanvasDag(name=canvas.name,
                           dag=_suite_dag(suite.skill_ids, body.confirm_side_effect))
        db.add(canvas)
        db.commit()
        db.refresh(canvas)
        suite.canvas_id = canvas.id
        db.commit()
    agent_run = await compile_and_run(db, canvas)
    summary = _summary_from_agent_run(db, agent_run)
    counts = summary["counts"]
    row = SuiteRun(suite_id=suite_id, results=summary["results"],
                   total=counts.get("total", len(summary["results"])),
                   pass_count=counts.get("pass", 0),
                   fail_count=counts.get("fail", 0),
                   error_count=counts.get("error", 0),
                   shadow_count=counts.get("shadow", 0),
                   agent_run_id=agent_run.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "suite_id": suite_id, "total": row.total,
            "pass_count": row.pass_count, "fail_count": row.fail_count,
            "error_count": row.error_count, "shadow_count": row.shadow_count,
            "results": summary["results"], "agent_run_id": agent_run.id,
            "created_at": row.created_at.isoformat()}


@router.get("/suites/{suite_id}/runs")
async def list_suite_runs(suite_id: int, db: Session = Depends(get_db)) -> list:
    rows = (db.query(SuiteRun).filter(SuiteRun.suite_id == suite_id)
            .order_by(SuiteRun.id.desc()).all())
    return [{"id": r.id, "suite_id": r.suite_id, "total": r.total,
             "pass_count": r.pass_count, "fail_count": r.fail_count,
             "error_count": r.error_count, "shadow_count": r.shadow_count,
             "results": r.results, "agent_run_id": r.agent_run_id,
             "created_at": r.created_at.isoformat()} for r in rows]
