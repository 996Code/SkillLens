"""AR2 ScenarioRun domain service: closure snapshot, idempotent creation,
server-side sequential execution with blocked semantics and C1 short-circuit."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import ReplayRun, Scenario, ScenarioRun, Skill, utcnow

MAX_DEPTH = 3
TERMINAL = {"pass", "fail", "error", "shadow", "aborted"}


def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def request_fingerprint(scenario_id: int, definition_version: int,
                        executor: str, confirm_side_effect, trigger: str,
                        requester: int | None) -> str:
    return hashlib.sha256(canonical_json({
        "scenario_id": scenario_id,
        "definition_version": definition_version,
        "executor": executor,
        "confirm_side_effect": confirm_side_effect,
        "trigger": trigger,
        "requester": requester,
    }).encode("utf-8")).hexdigest()


@dataclass
class ClosureStep:
    execution_index: int
    skill_id: int
    source_path: list[dict]
    step: dict


def build_closure(db: Session, scenario: Scenario) -> dict:
    """递归展开根场景为不可变闭包快照（occurrence 可区分、子版本定格）。"""
    scenarios = {s.id: s for s in db.query(Scenario).all()}

    leaves: list[dict] = []

    def walk(node: Scenario, entry: list[dict], depth: int,
             inherit_setup: bool) -> None:
        if depth > MAX_DEPTH:
            raise ValueError("子场景嵌套超过深度 3（疑似环）")
        for local_index, st in enumerate(node.steps or []):
            child_id = st.get("scenario_id")
            here = {"scenario_id": node.id, "local_index": local_index,
                    "version": node.definition_version}
            if child_id is not None:
                child = scenarios.get(child_id)
                if child is None or child.status != "active":
                    continue  # 已删/已归档子场景跳过（不致命）
                walk(child, entry + [here], depth + 1,
                     inherit_setup or bool(st.get("setup")))
                continue
            merged = dict(st)
            if inherit_setup:
                merged["setup"] = True
            if not merged.get("enabled", True):
                continue
            leaves.append({
                "execution_index": len(leaves),
                "skill_id": st["skill_id"],
                "source_path": entry + [here],
                "step": merged,
            })

    walk(scenario, [], 0, False)
    return {
        "root": {"scenario_id": scenario.id,
                 "definition_version": scenario.definition_version},
        "steps": leaves,
    }


# 场景级 C1 闸的写判定兜底词表：骨架无网络签名（经典表单整页提交录制
# 盲区——Dolibarr 4 技能实证）时按 click label 词表判写。业务动作词与
# AM1 词表同源（save/submit/create/confirm/add 族；刻意排除「确定/搜索」
# 防误报）。
_WRITE_LABEL_RE = None


def _init_write_label_re():
    global _WRITE_LABEL_RE
    import re
    _WRITE_LABEL_RE = re.compile(
        r"save|submit|create|confirm|add|new|delete|remove|update|"
        r"保存|提交|创建|新增|新建|删除|确认|添加|更新|生成|下单|订单|发票",
        re.IGNORECASE)


def _skill_writes(db: Session, steps: list[dict]) -> bool:
    from app.replay.plan import requires_confirmation
    skill_ids = {s["skill_id"] for s in steps}
    rows = db.query(Skill.id, Skill.skeleton).filter(Skill.id.in_(skill_ids)).all()
    for _, skeleton in rows:
        if requires_confirmation(skeleton or []):
            return True
        if _WRITE_LABEL_RE is None:
            _init_write_label_re()
        for st in skeleton or []:
            # 骨架步可能是 {"signature": "click:新建合作方"} 形态（无 kind/
            # label 字段）——文本合并匹配，不限定结构
            text = str(st.get("label") or "") + str(st.get("signature") or "")
            if _WRITE_LABEL_RE.search(text):
                return True
    return False


def create_scenario_run(
    db: Session, scenario: Scenario, *, executor: str, confirm_side_effect: bool,
    trigger: str, idempotency_key: str, fingerprint: str,
    requested_by: int | None, auto_status: str | None = None,
) -> tuple[ScenarioRun, bool]:
    """幂等创建：同键同指纹返回原行（created=False）；同键异指纹由调用方 409。"""
    existing = db.query(ScenarioRun).filter(
        ScenarioRun.idempotency_key == idempotency_key).first()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ConflictError(f"idempotency key 已用于不同请求：{idempotency_key}")
        return existing, False

    closure = build_closure(db, scenario)
    if not closure["steps"]:
        raise ValueError("场景闭包为空（无启用步骤）")
    has_writes = _skill_writes(db, closure["steps"])
    from app.reports.service import snapshot_expectations
    run = ScenarioRun(
        scenario_id=scenario.id,
        definition_version=scenario.definition_version,
        definition_snapshot=closure,
        expectation_snapshot=snapshot_expectations(db, scenario.id, closure),
        trigger=trigger,
        executor=executor,
        mode="execute" if confirm_side_effect else "shadow",
        status="queued",
        source_track="demo",
        confirm_side_effect=confirm_side_effect,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        requested_by_user_id=requested_by,
    )
    if auto_status in TERMINAL:
        run.status = auto_status
        run.started_at = utcnow()
        run.finished_at = utcnow()
    db.add(run)
    try:
        db.commit()
    except Exception:
        db.rollback()
        again = db.query(ScenarioRun).filter(
            ScenarioRun.idempotency_key == idempotency_key).first()
        if again is not None and again.request_fingerprint == fingerprint:
            return again, False
        raise
    db.refresh(run)
    if auto_status in TERMINAL:
        from app.reports.service import generate_report
        generate_report(db, run)
        db.refresh(run)
    return run, True


class ConflictError(Exception):
    pass


def finish_scenario_run(db: Session, run: ScenarioRun, status: str,
                        auto_report: bool = False) -> ScenarioRun:
    """终态收敛：相同终态幂等；冲突终态 409（由 API 层转）。

    AR4：auto_report=True 时终态后自动生成场景报告（幂等）。
    """
    if status not in TERMINAL:
        raise ValueError(f"非法终态：{status}")
    was_terminal = run.status in TERMINAL
    if was_terminal:
        if run.status == status:
            if auto_report:
                from app.reports.service import generate_report
                generate_report(db, run)
            return run
        raise ConflictError(
            f"scenario_run {run.id} 已终态 {run.status}，拒绝改为 {status}")
    run.status = status
    run.finished_at = utcnow()
    db.commit()
    db.refresh(run)
    if auto_report:
        from app.reports.service import generate_report
        generate_report(db, run)
        db.refresh(run)
    return run


def recompute_counts(db: Session, run: ScenarioRun,
                     blocked: int, statuses: list[str]) -> None:
    """父计数由服务端从闭包与子 ReplayRun 推导（不信任插件汇总）。"""
    run.pass_count = sum(1 for s in statuses if s == "pass")
    run.fail_count = sum(1 for s in statuses if s == "fail")
    run.error_count = sum(1 for s in statuses if s == "error")
    run.shadow_count = sum(1 for s in statuses if s == "shadow")
    run.blocked_count = blocked
    run.total_count = run.pass_count + run.fail_count + run.error_count \
        + run.shadow_count + blocked


async def execute_scenario_run(db: Session, run: ScenarioRun) -> ScenarioRun:
    """服务端顺序执行：逐步挂归属列；业务步失败后 blocked；C1 shadow 短路。"""
    from app.replay.runner import run_replay
    from app.replay.scenario_runner import resolve_step_overrides

    snapshot = run.definition_snapshot
    steps = snapshot["steps"]
    run.status = "running"
    run.started_at = utcnow()
    db.commit()

    # C1：未确认且含写技能 → 整场景 shadow，不触任何执行器
    if run.confirm_side_effect is False and _skill_writes(db, steps):
        statuses: list[str] = []
        for s in steps:
            rr = ReplayRun(skill_id=s["skill_id"], mode="shadow", status="shadow",
                           plan={"steps": [], "scenario_shadow": True},
                           executed=None, assertion_results=None,
                           executor="server", scenario_run_id=run.id,
                           execution_index=s["execution_index"], attempt=1,
                           scope_kind="scenario")
            db.add(rr)
            statuses.append("shadow")
        db.commit()
        recompute_counts(db, run, 0, statuses)
        return finish_scenario_run(db, run, "shadow", auto_report=True)

    import time as _time
    run_ts = int(_time.time() * 1000)
    step_ctx: list = []
    statuses = []
    blocked = 0
    stopped = False
    for s in steps:
        if stopped:
            blocked += 1
            continue
        ovr = resolve_step_overrides(s["step"], step_ctx, run_ts)
        try:
            rr = await run_replay(db, s["skill_id"], ovr,
                                  bool(run.confirm_side_effect))
            rr.scenario_run_id = run.id
            rr.execution_index = s["execution_index"]
            rr.attempt = 1
            rr.scope_kind = "scenario"
            db.commit()
            step_ctx.append((rr.plan or {}).get("observed") or [])
            statuses.append(rr.status)
        except Exception as exc:
            step_ctx.append([])
            statuses.append("error")
            run.failure_summary = {"step": s["execution_index"],
                                   "error": str(exc)[:200]}
        last = statuses[-1]
        if last != "pass" and not s["step"].get("setup"):
            stopped = True  # 业务步失败：后续 blocked（不落占位 run）

    recompute_counts(db, run, blocked, statuses)
    if statuses and all(x == "pass" for x in statuses):
        final = "pass"
    elif statuses and statuses[-1] == "shadow":
        final = "shadow"
    elif any(x == "error" for x in statuses):
        final = "error"
    else:
        final = "fail"
    return finish_scenario_run(db, run, final, auto_report=True)
