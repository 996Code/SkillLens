"""Skill 卡片聚合端点（S9 块C Task 1）：一次请求给前端全量概要。

GET /api/v1/skills/{id}/card → skill 概要 + skeleton + 变量 + 断言行 +
最近一条 replay_run 概要（含 shadow，按 id 倒序第一条）+ 对齐窗口参数。
避免工作台列表/详情页拼 N 次请求。

S12 N4 层5：GET /api/v1/skills/{id}/consistency → 聚合该 skill 全部
replay_run（assertion_results 非空）的各断言历史观测值集合与一致性判定。
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
            "flaky": bool(run.flaky), "ts": run.created_at.isoformat()}


@router.get("/skills/{skill_id}/flow")
async def get_skill_flow(skill_id: int, db: Session = Depends(get_db)) -> dict:
    """S39 操作流程图：骨架步骤+断言 → 节点+边（流程图基座）。
    Skill 详情以图呈现，不再是表格。"""
    from app.replay.flow_graph import build_skill_flow
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    return build_skill_flow(skill)


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
        # S15：superseded 行返回 200 + superseded_by（前端提示用）；活跃行为 None
        "superseded_by": skill.superseded_by,
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


def _assertion_signature(kind: str, payload: dict) -> tuple:
    """断言 ↔ 回放结果行的匹配签名，与 outcome.generate_assertions 的去重键同构：
    (kind, api_template, field/label)。assert_eval 结果行不带 assertion_id，
    只能按签名匹配（payload 可能被层4 verify 加 layer4_verified，不能整包比对）。"""
    return (kind, payload.get("api_template") or "",
            payload.get("field") or payload.get("label") or "")


# 层5 简化（S12 N4）：assert_eval 结果行不存字段值，state_signal 的一致性
# 实测为 HTTP status 一致性；字段值级一致性待断言结果行扩展后升级。
@router.get("/skills/{skill_id}/consistency")
async def get_skill_consistency(skill_id: int, db: Session = Depends(get_db)) -> dict:
    """S12 N4 层5：同 skill 多次 replay 的断言观测值一致性检查。

    观测值取结果行的 observed_status（state_signal/api_status 有网络观测）；
    observed_status 为 None 的行（ui_text/field_change/未命中模板）无观测 → 跳过。
    consistent = 该断言全部历史观测值相同；无任何观测的断言不输出。
    """
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    assertions = db.query(OutcomeAssertion).filter(
        OutcomeAssertion.skill_id == skill_id).order_by(OutcomeAssertion.id).all()
    run_results = [r.assertion_results for r in
                  db.query(ReplayRun).filter(ReplayRun.skill_id == skill_id).all()
                  if r.assertion_results]
    out = []
    for a in assertions:
        sig = _assertion_signature(a.kind, a.payload or {})
        # assert_eval 结果行不含 kind（只有 payload/observed_status/passed），
        # 匹配键退化为 (api_template, field_key)——该二元组在断言域内唯一
        # （api_status 无 field→""，state_signal 有 field，ui_text 有 label）。
        a_key = ((a.payload or {}).get("api_template", ""),
                 (a.payload or {}).get("field") or (a.payload or {}).get("label") or "")
        values = [row.get("observed_status") for results in run_results
                  for row in results
                  if row.get("observed_status") is not None
                  and ((row.get("payload") or {}).get("api_template", ""),
                       (row.get("payload") or {}).get("field")
                       or (row.get("payload") or {}).get("label") or "") == a_key]
        if not values:
            continue
        out.append({"assertion_id": a.id, "kind": a.kind,
                    "observed_values": values,
                    "consistent": len(set(values)) == 1})
    inconsistent = [r for r in out if not r["consistent"]]
    # S24 块 U：flaky 回放计数（首试 fail 重试 pass——不稳定信号进一致性视图）
    flaky_runs = len([r for r in
                      db.query(ReplayRun).filter(
                          ReplayRun.skill_id == skill_id,
                          ReplayRun.flaky.is_(True)).all()])
    return {"skill_id": skill_id, "runs": len(run_results), "assertions": out,
            "consistent": not inconsistent, "inconsistent_count": len(inconsistent),
            "flaky_runs": flaky_runs}
