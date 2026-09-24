"""Skill 卡片聚合端点（S9 块C Task 1）：一次请求给前端全量概要。

GET /api/v1/skills/{id}/card → skill 概要 + skeleton + 变量 + 断言行 +
最近一条 replay_run 概要（含 shadow，按 id 倒序第一条）+ 对齐窗口参数。
避免工作台列表/详情页拼 N 次请求。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, ReplayRun, Skill, SkillStrategy

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _last_run(db: Session, skill_id: int) -> dict | None:
    run = db.execute(
        select(ReplayRun).where(ReplayRun.skill_id == skill_id)
        .order_by(ReplayRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return {"id": run.id, "status": run.status, "mode": run.mode,
            "ts": run.created_at.isoformat()}


@router.get("/skills/{skill_id}/card")
async def get_skill_card(skill_id: int, db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    assertions = db.query(OutcomeAssertion).filter(
        OutcomeAssertion.skill_id == skill_id).order_by(OutcomeAssertion.id).all()
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "status": skill.status,
        "confidence": skill.confidence,
        "evidence_count": skill.evidence_count,
        "alignment_id": skill.alignment_id,
        "skeleton": skill.skeleton or [],
        "input_variables": skill.input_variables or [],
        "param_variables": skill.param_variables or [],
        "assertions": [{"id": a.id, "kind": a.kind, "layer": a.layer,
                        "payload": a.payload} for a in assertions],
        "last_run": _last_run(db, skill_id),
        "window_params": (db.get(Alignment, skill.alignment_id).window_params
                          if skill.alignment_id else None),
        "strategies": [{"signature": s.strategy_signature[:200],
                        "evidence_count": s.evidence_count}
                       for s in db.query(SkillStrategy).filter(
                           SkillStrategy.skill_id == skill_id).all()],
        "notes": skill.notes,
    }
