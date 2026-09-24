"""演示基线指标 API（Task 5）：为 C2「真实流量置信度 ≥ 演示基线 80%」提供对比锚。

assertion_pass_rate 取该 skill 最近一条 assertion_results 非空的 replay_run 的
passed 比例（shadow/异常 run 的 assertion_results 为 NULL，不参与；无任何有效
run 时为 null——outcome_assertion 行不存历史，replay_run 是唯一可靠来源）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, ReplayRun, Skill

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _latest_pass_rate(db: Session, skill_id: int) -> float | None:
    run = db.execute(
        select(ReplayRun).where(ReplayRun.skill_id == skill_id,
                                ReplayRun.assertion_results.is_not(None))
        .order_by(ReplayRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    results = run.assertion_results or []
    if not results:
        return None
    passed = sum(1 for r in results if r.get("passed"))
    return round(passed / len(results), 4)


def _baseline_item(db: Session, skill: Skill) -> dict:
    assertion_count = db.query(OutcomeAssertion).filter(
        OutcomeAssertion.skill_id == skill.id).count()
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "status": skill.status,
        "confidence": skill.confidence,
        "evidence_count": skill.evidence_count,
        "assertion_count": assertion_count,
        "assertion_pass_rate": _latest_pass_rate(db, skill.id),
        "input_var_names": [v.get("name") for v in skill.input_variables or []
                            if v.get("name")],
        "window_params": (db.get(Alignment, skill.alignment_id).window_params
                          if skill.alignment_id else None),
    }


@router.get("/baseline/skills")
async def list_baseline_skills(db: Session = Depends(get_db)) -> list:
    rows = db.query(Skill).order_by(Skill.id).all()
    return [_baseline_item(db, s) for s in rows]


@router.get("/baseline/skills/{skill_id}")
async def get_baseline_skill(skill_id: int, db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    return _baseline_item(db, skill)
