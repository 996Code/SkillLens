from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.change.expected import generate_expected_delta, link_discoveries, verify_delta
from app.db import SessionLocal
from app.models import ExpectedDelta, ReplayRun

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
    reviewed_by: str
    changes: list[dict] | None = None


@router.post("/expected-deltas", status_code=201)
async def create_expected(body: CreateDeltaRequest, db: Session = Depends(get_db)) -> dict:
    row = generate_expected_delta(db, body.requirement_text, body.requirement_id)
    if body.external_ref:
        row.external_ref = body.external_ref
        db.commit()
        db.refresh(row)
    return {"id": row.id, "status": row.status, "changes": row.changes, "notes": row.notes,
            "external_ref": row.external_ref}


@router.post("/expected-deltas/{delta_id}/confirm")
async def confirm_expected(delta_id: int, body: ConfirmRequest,
                           db: Session = Depends(get_db)) -> dict:
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
    row.reviewed_by = body.reviewed_by
    db.commit(); db.refresh(row)
    # S12 N2：确认成功后先验对齐——changes 与 discovered_feature 匹配 → linked
    linked = link_discoveries(db, row)
    return {"id": row.id, "status": row.status, "changes": row.changes,
            "linked_discoveries": linked}


class ObserveRequest(BaseModel):
    skill_id: int
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/expected-deltas/{delta_id}/observe", status_code=201)
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


@router.post("/expected-deltas/{delta_id}/report", status_code=201)
async def report(delta_id: int, body: ReportRequest,
                 db: Session = Depends(get_db)) -> dict:
    from app.change.classify import classify_delta
    from app.change.perf import perf_context
    from app.integrations.webhook import notify
    from app.models import DeltaReport, ObservedDelta
    delta = db.get(ExpectedDelta, delta_id)
    obs = db.get(ObservedDelta, body.observed_delta_id)
    if not delta or not obs:
        raise HTTPException(404, "expected/observed delta not found")
    if obs.expected_delta_id != delta_id:
        raise HTTPException(409, "observed delta 不属于该 expected delta")
    r = classify_delta(delta.changes, obs.items)

    # S23 块 V：性能漂移判定（确定性，perf_context 与 /reports/{id}/perf 共用）
    perf_ctx, perf_drifts = perf_context(db, obs.skill_id, obs.replay_run_id)
    r["drift"].extend(perf_drifts)

    row = DeltaReport(expected_delta_id=delta_id, observed_delta_id=obs.id,
                      expected=r["expected"], missing=r["missing"],
                      unexpected=r["unexpected"], drift=r["drift"])
    db.add(row); db.commit(); db.refresh(row)
    # S25 块 W2：报告生成推送（fire-and-forget，失败不阻塞）
    await notify(
        f"SkillLens 报告生成 #{row.id}",
        f"需求 {delta.requirement_id}：expected {len(r['expected'])} / "
        f"missing {len(r['missing'])} / unexpected {len(r['unexpected'])} / "
        f"drift {len(r['drift'])}")
    return {"id": row.id, "expected_delta_id": delta_id,
            "observed_delta_id": obs.id, "perf": perf_ctx, **r}


@router.get("/expected-deltas/{delta_id}")
async def get_expected(delta_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    return {"id": row.id, "requirement_id": row.requirement_id,
            "external_ref": row.external_ref,
            "feature": row.feature, "changes": row.changes, "status": row.status,
            "reviewed_by": row.reviewed_by, "notes": row.notes}
