"""S17 块 L：通用能力层 API（generic_skill）。

- POST /generic-skills/induce {skill_ids}：≥2 个非 superseded 源 skill →
  LLM 归纳 + 确定性回查 → candidate 落库（回查失败 notes 记原因）。
- GET /generic-skills：列表（id 倒序）；GET /generic-skills/{id}：详情。
- POST /generic-skills/{id}/promote：晋升纪律（双系统 + 各源回放 PASS）→
  learned，否则 409 带原因。
- POST /generic-skills/{id}/map {target_skill_id}：槽位映射探测（确定性），
  200 返回 {mapping, complete, gaps}——映射是探测不是断言，填不满不 409。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.learning.generic import induce_generic, map_generic, promote_generic
from app.models import GenericSkill, Skill

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class InduceRequest(BaseModel):
    skill_ids: list[int] = Field(min_length=2)   # <2 → 422（通用能力必须跨源）


class MapRequest(BaseModel):
    target_skill_id: int


def _item(row: GenericSkill) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "status": row.status,
        "slots_schema": row.slots_schema,
        "source_skill_ids": row.source_skill_ids,
        "evidence_refs": row.evidence_refs,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
    }


def _load_sources(db: Session, skill_ids: list[int]) -> list[Skill]:
    """源 skill 校验：不存在 404；superseded 409（不可作为归纳源）。"""
    skills = []
    for sid in skill_ids:
        skill = db.get(Skill, sid)
        if not skill:
            raise HTTPException(status_code=404, detail=f"skill {sid} not found")
        if skill.status == "superseded":
            raise HTTPException(
                status_code=409,
                detail=f"skill {sid} 已被取代（v{skill.superseded_by}），不可作为归纳源")
        skills.append(skill)
    return skills


@router.post("/generic-skills/induce")
async def induce(body: InduceRequest, db: Session = Depends(get_db)) -> dict:
    skills = _load_sources(db, body.skill_ids)
    return _item(induce_generic(db, skills))


@router.get("/generic-skills")
async def list_generic_skills(db: Session = Depends(get_db)) -> list:
    rows = db.query(GenericSkill).order_by(GenericSkill.id.desc()).all()
    return [_item(r) for r in rows]


@router.get("/generic-skills/{generic_id}")
async def get_generic_skill(generic_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(GenericSkill, generic_id)
    if not row:
        raise HTTPException(status_code=404, detail="generic skill not found")
    return _item(row)


@router.post("/generic-skills/{generic_id}/promote")
async def promote(generic_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(GenericSkill, generic_id)
    if not row:
        raise HTTPException(status_code=404, detail="generic skill not found")
    ok, why = promote_generic(db, row)
    if not ok:
        raise HTTPException(status_code=409, detail=why)
    row.status = "learned"
    db.commit()
    db.refresh(row)
    return _item(row)


@router.post("/generic-skills/{generic_id}/map")
async def map_to_skill(generic_id: int, body: MapRequest,
                       db: Session = Depends(get_db)) -> dict:
    row = db.get(GenericSkill, generic_id)
    if not row:
        raise HTTPException(status_code=404, detail="generic skill not found")
    target = db.get(Skill, body.target_skill_id)
    if not target:
        raise HTTPException(status_code=404, detail="target skill not found")
    return map_generic(row, target)
