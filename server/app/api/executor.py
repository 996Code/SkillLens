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


def _reap_stale_runs(db: Session) -> int:
    """协议 §5 心跳兜底：extension run 卡 running 超 10 分钟（无新步
    上报——矩阵实证 885/888 卡死）→ lost。在 /executor/skills 访问时
    顺带收割（无独立进程）。"""
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    rows = db.query(ReplayRun).filter(
        ReplayRun.executor == "extension",
        ReplayRun.status == "running",
        ReplayRun.created_at < cutoff).all()
    n = 0
    for r in rows:
        r.status = "lost"
        n += 1
    if n:
        db.commit()
    return n


@router.get("/executor/skills")
async def list_executor_skills(db: Session = Depends(get_db)) -> list:
    _reap_stale_runs(db)
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
            # AG5 行锚：labels 里的宿主行文本（>6 字符含 ASCII alnum，
            # ≠label——runner row-trigger 同门）编译进候选尾
            row_texts = [l for l in (step.get("labels") or [])
                         if len(l) > 6 and l != (step.get("label") or "")
                         and any(c.isascii() and c.isalnum() for c in l)]
            row_anchor = row_texts[0] if row_texts else None
            out.append({"seq": seq, "op": "click",
                        "label": step.get("label"),
                        "labels": step.get("labels") or [],
                        "tag": step.get("tag"),
                        "resolve_candidates": compile_resolve_candidates(
                            step.get("label") or "", step.get("labels"),
                            tag=step.get("tag"), row_anchor=row_anchor),
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
    # P2：自愈数据链插件端等效——活跃提案（verified/promoted）的
    # proposed_label 编译进对应 click 步候选首位（服务端 runner 的
    # repair_map 语义）
    repair_map = load_repair_map(db, skill_id)
    if repair_map:
        for ins in instructions:
            if ins.get("op") == "click" and ins.get("label") in repair_map:
                rep = repair_map[ins["label"]]
                from app.replay.resolver import compile_resolve_candidates
                healed = compile_resolve_candidates(rep["label"], ins.get("labels"))
                ins["resolve_candidates"] = healed
                ins["label"] = rep["label"]
                ins["healed"] = True
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
         "evidence": {k: v for k, v in body.evidence.items()
                      if k != "screenshot"}})
    state["cursor"] = cursor + 1
    nxt = instructions[cursor + 1] if cursor + 1 < len(instructions) \
        else instructions[-1] if instructions else None

    # 证据链对齐服务端（S33）：截图落盘 artifacts/<run>-<seq>.png +
    # plan 记 step_screenshots（工作台出图白名单同源）；快照进
    # before/after_snapshot（对齐服务端 run.plan 形态）
    ev = body.evidence or {}
    cur_ins2 = instructions[cursor] if cursor < len(instructions) else {}
    if ev.get("screenshot"):
        try:
            import base64
            import os
            from pathlib import Path as _P
            art = os.environ.get(
                "REPLAY_ARTIFACT_DIR",
                str(_P(__file__).resolve().parents[3] / "artifacts"))
            d = _P(art) / f"ext-run-{run_id}"
            os.makedirs(d, exist_ok=True)
            fname = f"step-{body.seq}.png"
            (d / fname).write_bytes(base64.b64decode(ev["screenshot"]))
            meta = plan.get("step_screenshots") or {"dir": str(d), "files": []}
            if fname not in meta["files"]:
                meta["files"] = list(meta["files"]) + [fname]
            plan = {**plan, "step_screenshots": meta}
            run.artifact_path = str(d / fname)
        except Exception:
            pass  # 截图落盘失败不破坏步循环（C3 主体已留痕）
    if ev.get("page") and cur_ins2.get("op") == "snapshot":
        phase = cur_ins2.get("phase")
        if phase in ("before", "after"):
            plan = {**plan, f"{phase}_snapshot": ev["page"]}

    # 协议 §4 当轮 LLM 介入：miss 的是**当前步**（instructions[cursor]，
    # cursor 已推进故当前步=state.cursor-1）——heal/超限都作用当前步
    cur_idx = cursor  # = state["cursor"] - 1（推进前的当前步）
    cur_ins = instructions[cur_idx] if cur_idx < len(instructions) else None

    if (body.result == "miss" and cur_ins is not None
            and state.get("interventions", 0) < 2
            and cur_ins.get("label")):
        # 计数先行：介入是"尝试"——LLM 不可达/提案为空也占额度（超限
        # 判 fail 语义不依赖网关可用性）
        state["interventions"] = state.get("interventions", 0) + 1
        try:
            from app.models import LocateProposal
            from app.llm.gateway import acomplete
            import json as _json
            texts = [str(t) for t in (body.evidence.get("page_texts") or [])]
            forms = [str(f) for f in (body.evidence.get("form_labels") or [])]
            label = cur_ins["label"]
            prompt = (
                f"自动化回放中按钮定位失败。原标签：{label}\n"
                f"当前页面可见文本元素：{_json.dumps(texts + forms, ensure_ascii=False)}\n"
                "从上述元素中选出最可能对应同一操作的新标签，"
                "只输出标签文本本身，不要任何解释。")
            result = await acomplete(db, "locate_repair", prompt)
            proposed = (result.text or "").strip().strip('"').splitlines()[0].strip()[:100]
            if proposed and proposed != label:
                db.add(LocateProposal(skill_id=run.skill_id, step_label=label,
                                      proposed_label=proposed, status="proposed"))
                db.commit()
                from app.replay.resolver import compile_resolve_candidates
                healed = compile_resolve_candidates(proposed, cur_ins.get("labels"))
                # heal 当前步：指令改写+游标回退重试（seq 不推进）
                instructions[cur_idx] = {**cur_ins, "label": proposed,
                                         "resolve_candidates": healed,
                                         "healed": True}
                plan["executor_instructions"] = instructions
                state["cursor"] = cursor
                nxt = instructions[cur_idx]
        except Exception:
            pass  # 介入失败不破坏步循环（fail-open；C3 已留痕 received）

    # 协议 §4 超限语义：介入已用满再 miss → 判 fail 留下轮（跨 run 自愈）
    if (body.result == "miss"
            and state.get("interventions", 0) >= 2
            and cur_ins is not None and cur_ins.get("label")):
        run.plan = {**plan, "executor_state": state}
        run.status = "fail"
        db.commit()
        db.refresh(run)
        return {"instruction": {"seq": None, "op": "detach"},
                "intervention_exhausted": True}

    # 目标站不可达（UX 评审致命 2）：goto error → run 判 fail（不再让
    # 后续步骤在错误页上假执行）
    if (body.result == "error" and cur_ins is not None
            and cur_ins.get("op") == "goto"):
        run.plan = {**plan, "executor_state": state}
        run.status = "fail"
        run.attribution = str(body.evidence.get("error", ""))[:500]
        db.commit()
        db.refresh(run)
        return {"instruction": {"seq": None, "op": "detach"},
                "navigation_failed": True}

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
