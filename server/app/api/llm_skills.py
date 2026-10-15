from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.fieldchange import extract_field_changes
from app.learning.outcome import generate_assertions, verify_against_session
from app.learning.skill import induce_skill
from app.models import (FieldChange, OutcomeAssertion, RecordingSession,
                        ReplayRun, Skill)
from app.api.auth import WRITE_GUARD

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sessions/{session_id}/field-changes", dependencies=WRITE_GUARD)
async def run_field_changes(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = extract_field_changes(db, session_id)
    return {"field_changes": len(rows)}


@router.get("/sessions/{session_id}/field-changes")
async def list_field_changes(session_id: str, db: Session = Depends(get_db)) -> list:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db.query(FieldChange).filter(FieldChange.session_id == session_id).all()
    return [{"api_template": r.api_template, "before_seq": r.before_seq,
             "after_seq": r.after_seq, "changes": r.changes} for r in rows]


@router.post("/alignments/{alignment_id}/induce", dependencies=WRITE_GUARD)
async def induce(alignment_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models import Alignment
    if not db.get(Alignment, alignment_id):
        raise HTTPException(status_code=404, detail="alignment not found")
    skill = await induce_skill(db, alignment_id)
    return {"id": skill.id, "alignment_id": skill.alignment_id, "name": skill.name,
            "description": skill.description, "status": skill.status,
            "skeleton": skill.skeleton, "param_variables": skill.param_variables,
            "input_variables": skill.input_variables, "confidence": skill.confidence,
            "evidence_count": skill.evidence_count, "notes": skill.notes}


@router.get("/skills")
async def list_skills(db: Session = Depends(get_db)) -> list:
    from app.api.baseline import _session_sources, _skill_source
    from app.models import Alignment
    from app.system import skill_systems
    sources = _session_sources(db)
    alignments = {a.id: a for a in db.query(Alignment).all()}

    class _AlignLookup:
        """_skill_source 逐条 db.get 会 N+1——预载映射后零额外查询。"""
        def get(self, model, aid):
            return alignments.get(aid)

    def source_of(r: Skill) -> str:
        # 与 baseline._skill_source 同一实现（评审 #17：双源漂移消除）
        return _skill_source(_AlignLookup(), r, sources)

    # S15：列表默认排除 superseded（历史版本不进工作台列表）
    rows = db.query(Skill).filter(Skill.status.notin_(["superseded", "archived"])) \
        .order_by(Skill.id.desc()).all()
    # S38：目标系统（参考会话首条 navigation host 派生，批量一次）
    systems = skill_systems(db)
    return [{"id": r.id, "alignment_id": r.alignment_id, "name": r.name,
             "description": r.description, "status": r.status,
             "confidence": r.confidence, "evidence_count": r.evidence_count,
             "notes": r.notes, "source": source_of(r),
             "system": systems.get(r.id, "未知系统")} for r in rows]


@router.post("/skills/{skill_id}/assertions", dependencies=WRITE_GUARD)
async def create_assertions(skill_id: int, db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.status == "superseded":
        raise HTTPException(409, f"该 Skill 版本已被取代（v{skill.superseded_by}），请使用新版本")
    rows = generate_assertions(db, skill_id)
    return {"assertions": len(rows)}


class FromRunRequest(BaseModel):
    run_id: int


@router.post("/skills/{skill_id}/assertions/from-run", dependencies=WRITE_GUARD)
async def create_assertions_from_run(
        skill_id: int, body: FromRunRequest, db: Session = Depends(get_db)) -> dict:
    """P0-3 回放反哺：从 pass run 的 observed 写响应引导 api_status 断言
    （经典表单系统录制侧抓不到写请求的兜底通道）。"""
    from app.learning.outcome import bootstrap_from_run
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.status == "superseded":
        raise HTTPException(409, f"该 Skill 版本已被取代（v{skill.superseded_by}），请使用新版本")
    try:
        rows = bootstrap_from_run(db, skill_id, body.run_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"assertions": len(rows)}


@router.post("/assertions/{assertion_id}/verify", dependencies=WRITE_GUARD)
async def verify_assertion(assertion_id: int, db: Session = Depends(get_db)) -> dict:
    assertion = db.get(OutcomeAssertion, assertion_id)
    if not assertion:
        raise HTTPException(status_code=404, detail="assertion not found")
    skill = db.get(Skill, assertion.skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.status == "superseded":
        # S15 版本演化：superseded 行断言保留作历史但不可再验证——提示走新版本
        new_skill = db.get(Skill, skill.superseded_by) if skill.superseded_by else None
        new_version = new_skill.version if new_skill else "?"
        raise HTTPException(
            status_code=409,
            detail=f"该版本已被取代（v{new_version}），请验证新版本")
    result = verify_against_session(db, assertion_id)
    # S12 N4 层4：verify 通过即累加历史成功样本。累加放 API 层而非库函数
    # verify_against_session——保持库函数纯查询零写（回放评估走独立的
    # assert_eval.evaluate_assertions，与本端点无共享路径）。
    # 达 3 次在 payload 标 layer4_verified=true（晋升规则：历史成功样本背书）。
    if result["passed"]:
        assertion.evidence_count = (assertion.evidence_count or 0) + 1
        assertion.payload = {**assertion.payload,
                             "layer4_verified": assertion.evidence_count >= 3}
        db.commit()
    result["evidence_count"] = assertion.evidence_count
    return result


@router.get("/skills/{skill_id}/assertions")
async def list_assertions(skill_id: int, db: Session = Depends(get_db)) -> list:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    rows = db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).all()
    return [{"id": r.id, "skill_id": r.skill_id, "layer": r.layer, "kind": r.kind,
             "api_template": r.api_template, "payload": r.payload} for r in rows]


class BulkArchiveRequest(BaseModel):
    ids: list[int] = Field(min_length=1)


@router.post("/skills/bulk-archive", dependencies=WRITE_GUARD)
async def bulk_archive(body: BulkArchiveRequest, db: Session = Depends(get_db)) -> dict:
    """AI4 库治理：批量归档（status=archived——不物理删，supersede 同族
    语义；列表/执行端点排除）。Candidate 垃圾与无描述技能的清障通道。"""
    rows = db.query(Skill).filter(Skill.id.in_(body.ids)).all()
    n = 0
    for s in rows:
        if s.status in ("superseded", "archived"):
            continue
        s.status = "archived"
        n += 1
    db.commit()
    return {"archived": n, "requested": len(body.ids)}


@router.get("/skills/{skill_id}/runs")
async def skill_runs_history(skill_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """UI 批2：Skill 页 run 历史——轻量行列选择（plan 不加载，UI 批1 纪律），
    created_at 倒序取最近 50。"""
    from sqlalchemy import func as _f
    rows = db.query(
        ReplayRun.id, ReplayRun.skill_id, ReplayRun.status, ReplayRun.mode,
        ReplayRun.flaky, ReplayRun.failure_class, ReplayRun.duration_ms,
        ReplayRun.created_at,
        # 步数取 plan.$.steps：插件 run 的 executed 恒空（replay.py AM3 同源结论）
        _f.ifnull(_f.json_array_length(ReplayRun.plan, "$.steps"), 0),
    ).filter(ReplayRun.skill_id == skill_id
    ).order_by(ReplayRun.created_at.desc()).limit(50).all()
    return [{"id": r[0], "skill_id": r[1], "status": r[2], "mode": r[3],
             "flaky": bool(r[4]), "failure_class": r[5],
             "duration_ms": r[6], "created_at": r[7].isoformat(),
             "steps": r[8]} for r in rows]


@router.get("/skills/trends")
async def skill_trends(db: Session = Depends(get_db)) -> list[dict]:
    """AI4 趋势卡：按系统聚合最近 30 天回放 pass/fail（无 run 的系统不
    出现——趋势是执行健康度，不是库存量）。"""
    from datetime import datetime, timedelta
    from app.models import ReplayRun
    from app.system import skill_systems
    from app.change.failure_class import pass_rate
    since = datetime.utcnow() - timedelta(days=30)
    # UI 优化批1（性能）：列选择——只取聚合字段（plan 列数百 KB 不加载，
    # 2026-10-14 实测整行加载 2875 行 13.2s → 列选择 <0.1s）
    rows = db.query(
        ReplayRun.skill_id, ReplayRun.status, ReplayRun.failure_class
    ).filter(
        ReplayRun.created_at >= since,
        ReplayRun.status.in_(("pass", "fail", "error"))).all()
    systems = skill_systems(db, [r.skill_id for r in rows])
    # P0-3 空断言 pass 显性化：0 断言技能的 pass 是无判定通过（假 pass
    # 工厂可见性）——按 skill 批量取断言数
    skill_ids = {r.skill_id for r in rows}
    asserted = {a for a in db.execute(
        select(OutcomeAssertion.skill_id).where(
            OutcomeAssertion.skill_id.in_(skill_ids))).scalars()}
    agg: dict[str, dict] = {}
    for r in rows:
        sysname = systems.get(r.skill_id) or "通用"
        a = agg.setdefault(sysname, {"system": sysname, "runs": [],
                                     "total": 0, "pass": 0, "fail": 0,
                                     "e1_env": 0, "e2_infra": 0,
                                     "unverified_pass": 0})
        # 原始分类计数（透明度：环境失败可见但不进分母）
        if r.failure_class:
            a[r.failure_class] = a.get(r.failure_class, 0) + 1
        if r.status == "pass" and r.skill_id not in asserted:
            a["unverified_pass"] += 1
        a["runs"].append({"status": r.status,
                          "failure_class": r.failure_class})
    # 分母口径（AJ1）：E1/E2 不计——用 failure_class.pass_rate 统一算
    for a in agg.values():
        pr = pass_rate(a.pop("runs"))
        a["pass"] = pr["pass"]
        a["total"] = pr["total"]
        a["fail"] = pr["total"] - pr["pass"]
        a["rate"] = pr["rate"]
    return sorted(agg.values(), key=lambda x: -x["total"])


@router.post("/skills/{skill_id}/rollback", dependencies=WRITE_GUARD)
async def rollback_skill(skill_id: int, db: Session = Depends(get_db)) -> dict:
    """AJ4 一键回滚（mabl 时钟图标回滚的技能级版本链版——业界独有）：
    指定版本失效（archived），其 superseded 前任复活（learned）。
    链式指向保持可审计（archived 版本不物理删）。"""
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    prev_id = None
    for s in db.query(Skill).filter(Skill.alignment_id == skill.alignment_id).all():
        if s.superseded_by == skill_id and s.status == "superseded":
            prev_id = s.id
            break
    if prev_id is None:
        raise HTTPException(422, "无可回滚的前版本（supersede 链上无前任）")
    prev = db.get(Skill, prev_id)
    prev.status = "learned"
    prev.superseded_by = None
    skill.status = "archived"  # 失效后续版本（不删，审计保留）
    db.commit()
    return {"rolled_back_to": prev_id, "archived": skill_id}
