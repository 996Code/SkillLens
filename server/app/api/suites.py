"""S37-3 测试套件端点：操作流程组合 → 一键执行 → 汇总报告。

- POST /suites          创建（name + skill_ids；skill 必须存在）
- GET /suites           列表（含 skill 概要）
- GET /suites/{id}      详情
- DELETE /suites/{id}   删除
- POST /suites/{id}/run 一键执行（复用 run_replay_batch：browser 复用 +
                        批级 C1 门控——confirm=false 各流程走预演）
- GET /suites/{id}/runs 执行历史（倒序）
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Skill, SuiteRun, TestSuite
from app.replay.runner import run_replay_batch

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


def _suite_item(db: Session, s: TestSuite) -> dict:
    skills = [db.get(Skill, sid) for sid in (s.skill_ids or [])]
    return {
        "id": s.id, "name": s.name,
        "skill_ids": s.skill_ids or [],
        "skills": [{"id": sk.id, "name": sk.name, "status": sk.status}
                   for sk in skills if sk is not None],
        "created_at": s.created_at.isoformat(),
    }


@router.post("/suites")
async def create_suite(body: SuiteIn, db: Session = Depends(get_db)) -> dict:
    for sid in body.skill_ids:
        if db.get(Skill, sid) is None:
            raise HTTPException(status_code=422, detail=f"skill {sid} 不存在")
    row = TestSuite(name=body.name, skill_ids=body.skill_ids)
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
    skill_ids = suite.skill_ids or []
    if not skill_ids:
        raise HTTPException(status_code=422, detail="套件为空")
    runs = await run_replay_batch(db, skill_ids, {}, body.confirm_side_effect)
    results = []
    counts = {"pass": 0, "fail": 0, "error": 0, "shadow": 0}
    for r in runs:
        skill = db.get(Skill, r.skill_id)
        results.append({
            "skill_id": r.skill_id,
            "skill_name": skill.name if skill else f"#{r.skill_id}",
            "run_id": r.id, "status": r.status, "mode": r.mode,
        })
        counts[r.status] = counts.get(r.status, 0) + 1
    row = SuiteRun(suite_id=suite_id, results=results, total=len(results),
                   pass_count=counts["pass"], fail_count=counts["fail"],
                   error_count=counts["error"], shadow_count=counts["shadow"])
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "suite_id": suite_id, "total": row.total,
            "pass_count": row.pass_count, "fail_count": row.fail_count,
            "error_count": row.error_count, "shadow_count": row.shadow_count,
            "results": results,
            "created_at": row.created_at.isoformat()}


@router.get("/suites/{suite_id}/runs")
async def list_suite_runs(suite_id: int, db: Session = Depends(get_db)) -> list:
    rows = (db.query(SuiteRun).filter(SuiteRun.suite_id == suite_id)
            .order_by(SuiteRun.id.desc()).all())
    return [{"id": r.id, "suite_id": r.suite_id, "total": r.total,
             "pass_count": r.pass_count, "fail_count": r.fail_count,
             "error_count": r.error_count, "shadow_count": r.shadow_count,
             "results": r.results,
             "created_at": r.created_at.isoformat()} for r in rows]
