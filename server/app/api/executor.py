"""AG1 扩展执行器协议端点（docs/arch/extension-executor-protocol.md v0.1）。

插件=完整执行节点（用户在 popup 选择并点击执行），服务器=计划编译+判定。
- GET  /executor/skills：技能列表含 requires_confirmation（C1 确认卡元数据）；
- POST /executor/skills/{id}/plan：编译计划返回 run_id+首条指令；
- POST /executor/runs/{run_id}/step：证据上报→下一条指令（seq 幂等）；
- POST /executor/runs/{run_id}/finish：终态落库。

指令序列的确定性投影（compile_executor_plan）：
  goto(plan.url) → snapshot(before) → 每计划步[fill|click（带 resolve 前置）]
  → snapshot(after) → detach。
协议内部态（游标/已收证据/介入计数）存 run.plan["executor_state"]——run 即会话。
"""
import time

import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, RawEvent, ReplayRun, Skill
from app.replay.plan import compile_skeleton_plan, requires_confirmation
from app.replay.repair import load_repair_map
from app.replay.resolver import compile_resolve_candidates
from sqlalchemy import select

router = APIRouter()

DEFAULT_TIMEOUT_MS = 5000


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/executor/skills")
async def list_executor_skills(db: Session = Depends(get_db)) -> list:
    items = []
    for s in db.query(Skill).filter(Skill.status != "superseded").all():
        items.append({
            "id": s.id, "name": s.name, "status": s.status,
            "requires_confirmation": requires_confirmation(s.skeleton or []),
        })
    return items


class ExecutorPlanRequest(BaseModel):
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


def _load_plan_input(db: Session, skill: Skill):
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(select(RawEvent).where(RawEvent.session_id == ref_sid)
                      .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}} for r in rows]
    return compile_skeleton_plan(events, skill.skeleton, ref_sid,
                                 {}, skill.input_variables)


def compile_executor_plan(plan: dict) -> list[dict]:
    """计划步 → 微指令序列（确定性纯函数：同 plan 同序列）。"""
    seq = 1
    out: list[dict] = []
    if plan.get("url"):
        out.append({"seq": seq, "op": "goto", "url": plan["url"],
                    "timeout_ms": 15000})
        seq += 1
    out.append({"seq": seq, "op": "snapshot",
                "phase": "before", "scopes": ["labels", "forms", "toasts"],
                "timeout_ms": DEFAULT_TIMEOUT_MS})
    seq += 1
    for step in plan.get("steps", []):
        if step.get("kind") == "goto":
            out.append({"seq": seq, "op": "goto", "url": step["url"],
                        "timeout_ms": 15000})
        elif step.get("kind") == "input":
            out.append({"seq": seq, "op": "fill",
                        "name": step.get("name"), "value": step.get("value"),
                        "labels": step.get("labels") or [],
                        "resolve_candidates": compile_resolve_candidates(
                            step.get("name") or "", step.get("labels")),
                        "timeout_ms": DEFAULT_TIMEOUT_MS})
        elif step.get("kind") == "click":
            out.append({"seq": seq, "op": "click",
                        "label": step.get("label"),
                        "labels": step.get("labels") or [],
                        "tag": step.get("tag"),
                        "resolve_candidates": compile_resolve_candidates(
                            step.get("label") or "", step.get("labels"),
                            tag=step.get("tag")),
                        "timeout_ms": DEFAULT_TIMEOUT_MS})
        seq += 1
    out.append({"seq": seq, "op": "snapshot",
                "phase": "after", "scopes": ["labels", "forms", "toasts"],
                "timeout_ms": DEFAULT_TIMEOUT_MS})
    seq += 1
    out.append({"seq": seq, "op": "detach", "timeout_ms": DEFAULT_TIMEOUT_MS})
    return out


@router.post("/executor/skills/{skill_id}/plan")
async def executor_plan(skill_id: int, body: ExecutorPlanRequest,
                        db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    if skill.status == "superseded":
        raise HTTPException(409, "该 Skill 版本已被取代")
    if requires_confirmation(skill.skeleton or []) and not body.confirm_side_effect:
        raise HTTPException(409, "含写操作，需 C1 确认（confirm_side_effect=true）")

    plan = _load_plan_input(db, skill)
    instructions = compile_executor_plan(plan)
    state = {"cursor": 0, "received": [], "interventions": 0,
             "overrides": body.overrides}
    run = ReplayRun(skill_id=skill_id, mode="execute", status="running",
                    plan={"steps": plan.get("steps", []),
                          "url": plan.get("url", ""),
                          "executor_instructions": instructions,
                          "executor_state": state},
                    executor="extension")
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"run_id": run.id, "instruction": instructions[0],
            "total_instructions": len(instructions)}


class ExecutorStepReport(BaseModel):
    seq: int
    result: str
    evidence: dict = {}


@router.post("/executor/runs/{run_id}/step")
async def executor_step(run_id: int, body: ExecutorStepReport,
                        db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run or run.executor != "extension":
        raise HTTPException(404, "executor run not found")
    if run.status not in ("running",):
        raise HTTPException(409, f"run 已终态（{run.status}）")

    plan = run.plan or {}
    instructions = plan.get("executor_instructions") or []
    state = plan.get("executor_state") or {}
    cursor: int = state.get("cursor", 0)

    # 幂等：重复 seq（断连重放）丢弃，返回缓存指令不推进
    expected = instructions[cursor]["seq"] if cursor < len(instructions) else None
    if body.seq != expected:
        cached = instructions[cursor] if cursor < len(instructions) \
            else {"seq": None, "op": "detach"}
        return {"instruction": cached, "duplicate": True}

    # 证据归档（C3）。state 深拷贝后变异——直接变异 plan 内嵌 dict 会让
    # SQLAlchemy 的新旧值相等（别名同对象），UPDATE 不发（AG3 实证）
    import copy
    state = copy.deepcopy(state)
    state.setdefault("received", []).append(
        {"seq": body.seq, "result": body.result,
         "evidence": body.evidence})
    state["cursor"] = cursor + 1
    nxt = instructions[cursor + 1] if cursor + 1 < len(instructions) \
        else instructions[-1] if instructions else None
    run.plan = {**plan, "executor_state": state}
    db.commit()
    return {"instruction": nxt, "duplicate": False}


class ExecutorFinishRequest(BaseModel):
    status: str
    summary: dict = {}


@router.post("/executor/runs/{run_id}/finish")
async def executor_finish(run_id: int, body: ExecutorFinishRequest,
                          db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run or run.executor != "extension":
        raise HTTPException(404, "executor run not found")
    if body.status not in ("done", "fail", "aborted", "lost"):
        raise HTTPException(422, "status 须为 done|fail|aborted|lost")
    plan = run.plan or {}
    state = copy.deepcopy(plan.get("executor_state") or {})
    run.status = body.status
    run.executed = body.summary.get("executed")
    run.duration_ms = body.summary.get("duration_ms")

    # AG4：done 时服务端确定性断言——插件证据（observed/executed）喂
    # evaluate_assertions（原封不动），判定语义=执行+断言；status 重判
    assertion_results = None
    if body.status == "done":
        from app.models import OutcomeAssertion
        from app.replay.assert_eval import evaluate_assertions
        assertions = [{"kind": a.kind, "payload": a.payload} for a in
                      db.query(OutcomeAssertion).filter(
                          OutcomeAssertion.skill_id == run.skill_id).all()]
        observed = [{"url": o.get("url", ""), "status": o.get("status"),
                     "method": o.get("method", "GET"),
                     "body": str(o.get("body", ""))}
                    for o in body.summary.get("observed", [])]
        assertion_results = evaluate_assertions(
            assertions, observed,
            executed_steps=body.summary.get("executed") or [])
        run.assertion_results = assertion_results
        if all(a.get("passed") for a in assertion_results):
            run.status = "pass"
        else:
            run.status = "fail"

    run.plan = {**plan, "executor_state": state,
                "executor_summary": body.summary}
    if body.status in ("fail", "aborted", "lost"):
        run.attribution = str(body.summary.get("error", ""))[:500]
    db.commit()
    db.refresh(run)
    return {"id": run.id, "status": run.status, "executor": run.executor,
            "assertion_results": assertion_results}
