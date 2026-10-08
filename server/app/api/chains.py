"""AH1 链（chain）CRUD：链=纯数据，服务端只存不解释（规则在插件侧解释——
降耦合原则：不为任何系统写执行代码）。

- POST /chains          创建（name/system/steps）—— WRITE_GUARD
- GET /chains           列表（?system= 过滤；空间小窗按当前 tab 系统取）
- GET /chains/{id}      详情（steps 附技能概要：id/name/requires_confirmation，
                        小窗与 executor 链模式渲染用）
- DELETE /chains/{id}   删除 —— WRITE_GUARD
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Chain, Skill
from app.api.auth import WRITE_GUARD

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChainStepIn(BaseModel):
    skill_id: int
    overrides: dict[str, str] = Field(default_factory=dict)


class ChainIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    system: str = Field(min_length=1, max_length=40)
    steps: list[ChainStepIn] = Field(min_length=1)


def _validate_steps(db: Session, steps: list[ChainStepIn]) -> None:
    """skill_id 必须存在——技能删除后链不可静默悬空（创建时即拒绝）。"""
    for st in steps:
        if not db.get(Skill, st.skill_id):
            raise HTTPException(422, f"skill 不存在：{st.skill_id}")


def _skill_brief(db: Session, skill_id: int) -> dict:
    from app.replay.plan import requires_confirmation
    s = db.get(Skill, skill_id)
    return {"id": s.id, "name": s.name,
            "requires_confirmation": requires_confirmation(s.skeleton or [])}


@router.post("/chains", status_code=201, dependencies=WRITE_GUARD)
async def create_chain(body: ChainIn, db: Session = Depends(get_db)) -> dict:
    _validate_steps(db, body.steps)
    row = Chain(name=body.name, system=body.system,
                steps=[st.model_dump() for st in body.steps])
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "system": row.system,
            "steps": row.steps}


@router.get("/chains")
async def list_chains(system: str = "", db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(Chain)
    if system:
        q = q.filter(Chain.system == system)
    return [{"id": r.id, "name": r.name, "system": r.system,
             "steps": r.steps, "created_at": str(r.created_at)}
            for r in q.order_by(Chain.id.desc()).all()]


@router.get("/chains/{chain_id}")
async def get_chain(chain_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Chain, chain_id)
    if not row:
        raise HTTPException(404, "chain not found")
    steps = []
    for st in row.steps or []:
        brief = _skill_brief(db, st.get("skill_id", 0)) \
            if db.get(Skill, st.get("skill_id", 0)) else None
        steps.append({"skill_id": st.get("skill_id"),
                      "overrides": st.get("overrides") or {},
                      "skill": brief})
    return {"id": row.id, "name": row.name, "system": row.system,
            "steps": steps, "created_at": str(row.created_at)}


@router.delete("/chains/{chain_id}", dependencies=WRITE_GUARD)
async def delete_chain(chain_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Chain, chain_id)
    if not row:
        raise HTTPException(404, "chain not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
