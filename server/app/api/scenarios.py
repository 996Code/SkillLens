"""AR1 Scenario API: user-level business workflows."""
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import WRITE_GUARD
from app.db import SessionLocal
from app.models import Alignment, RawEvent, Scenario, Skill, utcnow

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ScenarioStepIn(BaseModel):
    skill_id: int | None = None
    scenario_id: int | None = None
    overrides: dict[str, str] = Field(default_factory=dict)
    setup: bool = False
    cleanup: dict | None = None
    enabled: bool = True
    row_anchor_from: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _exclusive_ids(self):
        if (self.skill_id is None) == (self.scenario_id is None):
            raise ValueError("skill_id 与 scenario_id 必须二选一")
        return self


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    system: str = Field(min_length=1, max_length=40)
    steps: list[ScenarioStepIn] = Field(min_length=1)


def _validate_steps(db: Session, steps: list[ScenarioStepIn],
                    current_id: int | None = None) -> None:
    for step in steps:
        if step.skill_id is not None and not db.get(Skill, step.skill_id):
            raise HTTPException(422, f"skill 不存在：{step.skill_id}")
        if step.scenario_id is not None:
            if step.scenario_id == current_id:
                raise HTTPException(422, "场景不能直接引用自身")
            ref = db.get(Scenario, step.scenario_id)
            if not ref or ref.status != "active":
                raise HTTPException(422, f"scenario 不存在或已归档：{step.scenario_id}")


def _fill_fields(db: Session, skill_id: int) -> list[dict]:
    skill = db.get(Skill, skill_id)
    fills: list[dict] = []
    if not skill or not skill.alignment_id:
        return fills
    try:
        alignment = db.get(Alignment, skill.alignment_id)
        session_id = (alignment.session_ids or [None])[0] if alignment else None
        if not session_id:
            return fills
        rows = db.execute(
            select(RawEvent).where(
                RawEvent.session_id == session_id,
                RawEvent.kind == "action",
            ).order_by(RawEvent.ts, RawEvent.seq)
        ).scalars().all()
        seen: set[str] = set()
        for row in rows:
            payload = row.payload or {}
            name = str(payload.get("name") or "")
            if payload.get("type") == "input" and name and name not in seen:
                seen.add(name)
                fills.append({"name": name,
                              "value": str(payload.get("value", ""))[:60]})
    except Exception:
        pass
    return fills


def _skill_brief(db: Session, skill_id: int) -> dict:
    from app.replay.plan import requires_confirmation

    skill = db.get(Skill, skill_id)
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description or "",
        "requires_confirmation": requires_confirmation(skill.skeleton or []),
        "fill_fields": _fill_fields(db, skill_id),
    }


def _summary(row: Scenario) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "system": row.system,
        "steps": row.steps,
        "status": row.status,
        "definition_version": row.definition_version,
        "origin": row.origin,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.post("/scenarios", status_code=201, dependencies=WRITE_GUARD)
async def create_scenario(body: ScenarioIn, db: Session = Depends(get_db)) -> dict:
    _validate_steps(db, body.steps)
    row = Scenario(
        name=body.name,
        system=body.system,
        steps=[step.model_dump() for step in body.steps],
        status="active",
        definition_version=1,
        origin="manual",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _summary(row)


@router.get("/scenarios")
async def list_scenarios(
    system: str = "",
    status: str = Query("active", pattern="^(active|archived|)$"),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = db.query(Scenario)
    if system:
        query = query.filter(Scenario.system == system)
    if status:
        query = query.filter(Scenario.status == status)
    return [_summary(row) for row in query.order_by(Scenario.id.desc()).all()]


@router.get("/skills/{skill_id}/fills")
async def skill_fill_fields(skill_id: int,
                            db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Skill, skill_id):
        raise HTTPException(404, "skill not found")
    return _fill_fields(db, skill_id)


@router.get("/skills/{skill_id}/scenario-references")
async def skill_scenario_references(skill_id: int,
                                    db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Skill, skill_id):
        raise HTTPException(404, "skill not found")
    out = []
    for scenario in db.query(Scenario).filter(Scenario.status == "active").all():
        for index, step in enumerate(scenario.steps or []):
            if step.get("skill_id") == skill_id:
                out.append({"scenario_id": scenario.id,
                            "scenario_name": scenario.name,
                            "step_index": index + 1,
                            "setup": bool(step.get("setup"))})
    return out


@router.get("/scenarios/{scenario_id}")
async def get_scenario(scenario_id: int,
                       db: Session = Depends(get_db)) -> dict:
    row = db.get(Scenario, scenario_id)
    if not row:
        raise HTTPException(404, "scenario not found")
    steps = []
    for step in row.steps or []:
        referenced_id = step.get("scenario_id")
        brief = None
        if referenced_id is not None:
            referenced = db.get(Scenario, referenced_id)
            brief = {
                "id": referenced_id,
                "name": referenced.name if referenced else "(已删)",
                "is_scenario": True,
            }
        elif step.get("skill_id") is not None and db.get(Skill, step["skill_id"]):
            brief = _skill_brief(db, step["skill_id"])
        steps.append({
            "skill_id": step.get("skill_id"),
            "scenario_id": referenced_id,
            "setup": bool(step.get("setup")),
            "enabled": step.get("enabled", True),
            "overrides": step.get("overrides") or {},
            "cleanup": step.get("cleanup"),
            "row_anchor_from": step.get("row_anchor_from"),
            "skill": brief,
        })
    result = _summary(row)
    result["steps"] = steps
    return result


@router.patch("/scenarios/{scenario_id}", dependencies=WRITE_GUARD)
async def update_scenario(
    scenario_id: int,
    body: ScenarioIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(Scenario, scenario_id)
    if not row:
        raise HTTPException(404, "scenario not found")
    if if_match is None:
        raise HTTPException(428, "If-Match definition_version required")
    try:
        version = int(if_match.strip('"'))
    except ValueError as exc:
        raise HTTPException(422, "If-Match must be an integer version") from exc
    if version != row.definition_version:
        raise HTTPException(409, {
            "message": "场景已被其他修改更新",
            "current_definition_version": row.definition_version,
        })
    if row.status != "active":
        raise HTTPException(409, "archived scenario is read-only")
    _validate_steps(db, body.steps, current_id=scenario_id)
    row.name = body.name
    row.system = body.system
    row.steps = [step.model_dump() for step in body.steps]
    row.definition_version += 1
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _summary(row)


@router.post("/scenarios/{scenario_id}/archive", dependencies=WRITE_GUARD)
async def archive_scenario(scenario_id: int,
                           db: Session = Depends(get_db)) -> dict:
    row = db.get(Scenario, scenario_id)
    if not row:
        raise HTTPException(404, "scenario not found")
    row.status = "archived"
    row.updated_at = utcnow()
    db.commit()
    db.refresh(row)
    return _summary(row)


@router.get("/scenarios/{scenario_id}/references")
async def scenario_references(scenario_id: int,
                              db: Session = Depends(get_db)) -> list[dict]:
    if not db.get(Scenario, scenario_id):
        raise HTTPException(404, "scenario not found")
    out = []
    for parent in db.query(Scenario).filter(Scenario.status == "active").all():
        for index, step in enumerate(parent.steps or []):
            if step.get("scenario_id") == scenario_id:
                out.append({"scenario_id": parent.id,
                            "scenario_name": parent.name,
                            "step_index": index + 1})
    return out


@router.post("/scenarios/{scenario_id}/run", dependencies=WRITE_GUARD)
async def run_scenario(
    scenario_id: int,
    wait: int = 0,
    confirm_side_effect: bool = True,
    db: Session = Depends(get_db),
) -> dict:
    """AR1 transition endpoint; AR2 replaces this with ScenarioRun creation."""
    if not db.get(Scenario, scenario_id):
        raise HTTPException(404, "scenario not found")
    if not wait:
        raise HTTPException(422, "当前仅支持 wait=1（同步执行）")
    from app.replay.scenario_runner import run_scenario_server

    result = await run_scenario_server(db, scenario_id, confirm_side_effect)
    if result.get("status") != "pass":
        raise HTTPException(409, result)
    return result
