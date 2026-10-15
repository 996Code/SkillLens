from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.change.expected import generate_expected_delta, link_discoveries, verify_delta
from app.db import SessionLocal
from app.models import ExpectedDelta, ReplayRun, User
from app.api.auth import WRITE_GUARD, require_role

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CreateDeltaRequest(BaseModel):
    requirement_id: str
    requirement_text: str
    external_ref: str | None = None   # S25 块 W3：Jira key 等外部条目编号


class ConfirmRequest(BaseModel):
    changes: list[dict] | None = None


@router.post("/expected-deltas", status_code=201, dependencies=WRITE_GUARD)
async def create_expected(body: CreateDeltaRequest, db: Session = Depends(get_db)) -> dict:
    row = await generate_expected_delta(db, body.requirement_text, body.requirement_id)
    if body.external_ref:
        row.external_ref = body.external_ref
        db.commit()
        db.refresh(row)
    return {"id": row.id, "status": row.status, "changes": row.changes, "notes": row.notes,
            "external_ref": row.external_ref}


@router.post("/expected-deltas/{delta_id}/confirm")
async def confirm_expected(delta_id: int, body: ConfirmRequest,
                           db: Session = Depends(get_db),
                           user: User = Depends(require_role("admin", "reviewer"))) -> dict:
    """C1 人工门：确认人取登录态——reviewed_by 若来自请求体则可被任意
    viewer 冒充 admin 完成确认，审计不可抵赖性失效。"""
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    if row.status == "confirmed":
        raise HTTPException(409, "已确认过，不可重复确认")
    if body.changes is not None:
        ok, why = verify_delta(body.changes)
        if not ok:
            raise HTTPException(422, why)
        row.changes = body.changes
    else:
        ok, why = verify_delta(row.changes)
        if not ok:
            raise HTTPException(422, f"当前 changes 无效（{why}），确认时必须提交修订")
    row.status = "confirmed"
    row.reviewed_by = user.username
    db.commit(); db.refresh(row)
    # S12 N2：确认成功后先验对齐——changes 与 discovered_feature 匹配 → linked
    linked = link_discoveries(db, row)
    return {"id": row.id, "status": row.status, "changes": row.changes,
            "linked_discoveries": linked}


class ObserveRequest(BaseModel):
    skill_id: int
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/expected-deltas/{delta_id}/observe", status_code=201, dependencies=WRITE_GUARD)
async def observe(delta_id: int, body: ObserveRequest,
                  db: Session = Depends(get_db)) -> dict:
    from app.models import Skill
    _skill = db.get(Skill, body.skill_id)
    if _skill and _skill.status == "superseded":
        raise HTTPException(409, f"该 Skill 版本已被取代（v{_skill.superseded_by}），请使用新版本")
    from app.change.observed import run_observe
    try:
        row = await run_observe(db, delta_id, body.skill_id,
                                body.overrides, body.confirm_side_effect)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return {"id": row.id, "items": row.items, "replay_run_id": row.replay_run_id,
            "replay_status": db.get(ReplayRun, row.replay_run_id).status}


class ReportRequest(BaseModel):
    observed_delta_id: int


@router.post("/expected-deltas/{delta_id}/report", status_code=201, dependencies=WRITE_GUARD)
async def report(delta_id: int, body: ReportRequest,
                 db: Session = Depends(get_db)) -> dict:
    raise HTTPException(
        status_code=410,
        detail="旧手工报告写入已由 AR1 冻结；AR4 将由 ScenarioRun 终态自动生成报告",
    )


@router.get("/expected-deltas")
async def list_expected_deltas(status: str = "confirmed",
                               db: Session = Depends(get_db)) -> list[dict]:
    """UI 批3：ReplayLaunch 下拉数据源——按状态列轻量行（changes 只取
    计数，SQL 端 json_array_length）。"""
    from sqlalchemy import func as _f
    rows = db.query(
        ExpectedDelta.id, ExpectedDelta.requirement_id,
        ExpectedDelta.feature, ExpectedDelta.version,
        ExpectedDelta.created_at,
        _f.ifnull(_f.json_array_length(ExpectedDelta.changes), 0),
    ).filter(ExpectedDelta.status == status
    ).order_by(ExpectedDelta.created_at.desc()).limit(50).all()
    return [{"id": r[0], "requirement_id": r[1], "feature": r[2],
             "version": r[3], "created_at": r[4].isoformat(),
             "change_count": r[5]} for r in rows]


@router.get("/expected-deltas/{delta_id}")
async def get_expected(delta_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    return {"id": row.id, "requirement_id": row.requirement_id,
            "external_ref": row.external_ref,
            "feature": row.feature, "changes": row.changes, "status": row.status,
            "reviewed_by": row.reviewed_by, "notes": row.notes}
