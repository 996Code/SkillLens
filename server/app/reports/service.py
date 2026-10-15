"""AR4 auto report generation for terminal ScenarioRuns."""
from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.models import (ExpectedDelta, ObservedDelta, ReplayRun, ReportDelta,
                        ScenarioExpectation, ScenarioReport, ScenarioRun, utcnow)
from app.scenario.service import canonical_json


def expectation_key(occurrence_path: list[dict], scenario_id: int,
                    scenario_version: int, expected_delta_id: int,
                    expected_version: int, step_index: int | None) -> str:
    return hashlib.sha256(canonical_json({
        "occurrence_path": occurrence_path,
        "scenario_id": scenario_id,
        "scenario_definition_version": scenario_version,
        "expected_delta_id": expected_delta_id,
        "expected_version": expected_version,
        "local_step_index": step_index,
    }).encode("utf-8")).hexdigest()


def snapshot_expectations(db: Session, scenario_id: int,
                          closure: dict) -> list[dict]:
    """创建运行时把活动绑定与期望内容定格进 expectation_snapshot。"""
    bindings = db.query(ScenarioExpectation).filter(
        ScenarioExpectation.scenario_id == scenario_id,
        ScenarioExpectation.active.is_(True)).all()
    if not bindings:
        return []
    deltas = {d.id: d for d in db.query(ExpectedDelta).filter(
        ExpectedDelta.id.in_([b.expected_delta_id for b in bindings]))}
    # 闭包内 scenario → occurrence 路径（根+每叶子 source_path 中间层）
    out = []
    for b in bindings:
        d = deltas.get(b.expected_delta_id)
        if d is None or d.status != "confirmed":
            continue
        # 绑定属于本场景（根）；occurrence_path 以根为起点
        out.append({
            "scenario_id": scenario_id,
            "scenario_definition_version": closure["root"]["definition_version"],
            "expected_delta_id": d.id,
            "expected_version": d.version,
            "requirement_id": d.requirement_id,
            "changes": d.changes or [],
            "local_step_index": b.step_index,
            "expectation_key": expectation_key(
                [{"scenario_id": scenario_id, "local_index": 0}],
                scenario_id, closure["root"]["definition_version"],
                d.id, d.version, b.step_index),
        })
    return out


def _effective_children(db: Session, run_id: int) -> dict[int, ReplayRun]:
    children = db.query(ReplayRun).filter(
        ReplayRun.scenario_run_id == run_id).all()
    best: dict[int, ReplayRun] = {}
    for c in children:
        idx = c.execution_index if c.execution_index is not None else -1
        cur = best.get(idx)
        if cur is None or c.attempt > cur.attempt:
            best[idx] = c
    return best


def _extract_observed_items(run: ReplayRun) -> list[dict]:
    """从子 run 已落库证据确定性提取观测项（不重跑浏览器）。

    观测来源：plan.observed（执行旁挂的写证据）∪ assertion_results 的
    api_status 模板。与 change/observed.py 的 run_observe 同源语义但纯读。
    """
    plan = run.plan or {}
    items: list[dict] = []
    for obs in plan.get("observed") or []:
        url = str(obs.get("url") or obs.get("api") or "")
        if url:
            items.append({"type": "api_add", "value": url,
                          "status": obs.get("status")})
    for a in run.assertion_results or []:
        tmpl = str((a or {}).get("api_template") or "")
        if tmpl:
            items.append({"type": "api_add", "value": tmpl,
                          "status": (a or {}).get("observed")})
    return items


def generate_report(db: Session, run: ScenarioRun) -> ScenarioReport:
    """终态运行生成报告：幂等（已有 ready/generating 直接补全/返回）。"""
    existing = db.query(ScenarioReport).filter(
        ScenarioReport.scenario_run_id == run.id).first()
    report = existing or ScenarioReport(
        scenario_run_id=run.id, status="generating",
        coverage_state="no_expectation", source_track=run.source_track)
    db.add(report)
    db.flush()
    report.attempt_count += 0 if existing else 0
    report.last_attempt_at = utcnow()

    try:
        bindings = run.expectation_snapshot or []
        if not bindings:
            report.coverage_state = "no_expectation"
            report.status = "ready"
            report.finished_at = utcnow()
            db.commit()
            db.refresh(report)
            return report

        best = _effective_children(db, run.id)
        closure_steps = (run.definition_snapshot or {}).get("steps") or []
        by_local: dict[int, list[ReplayRun]] = {}
        for s in closure_steps:
            path = s.get("source_path") or []
            # 该叶子所属的直接场景（source_path 末项）与其局部索引
            if not path:
                continue
            owner = path[-1]
            if owner.get("scenario_id") == run.scenario_id:
                by_local.setdefault(owner.get("local_index"), []).append(
                    best.get(s["execution_index"]))

        # 清旧明细再重建（retry 幂等 upsert 语义）
        db.query(ReportDelta).filter(
            ReportDelta.scenario_report_id == report.id).delete()

        totals = {"expected": 0, "missing": 0, "unexpected": 0, "drift": 0}
        from app.change.classify import classify_delta
        for b in bindings:
            local = b.get("local_step_index")
            runs = ([r for r in by_local.get(local, []) if r]
                    if local is not None
                    else [r for rs in by_local.values() for r in rs if r])
            items: list[dict] = []
            run_ids: list[int] = []
            for r in runs:
                items.extend(_extract_observed_items(r))
                run_ids.append(r.id)
            result = classify_delta(b.get("changes") or [], items)
            for k in ("expected", "missing", "unexpected", "drift"):
                totals[k] += len(result[k])
            db.add(ReportDelta(
                scenario_report_id=report.id,
                expectation_key=b["expectation_key"],
                expected_delta_id=b["expected_delta_id"],
                observed_delta_ids=[],
                evidence_replay_run_ids=run_ids,
                expected=result["expected"], missing=result["missing"],
                unexpected=result["unexpected"], drift=result["drift"]))
        report.expected_count = totals["expected"]
        report.missing_count = totals["missing"]
        report.unexpected_count = totals["unexpected"]
        report.drift_count = totals["drift"]
        report.coverage_state = "complete"
        report.status = "ready"
        report.error_code = None
        report.error_summary = None
        report.finished_at = utcnow()
        db.commit()
        db.refresh(report)
        return report
    except Exception as exc:
        db.rollback()
        fresh = db.query(ScenarioReport).filter(
            ScenarioReport.scenario_run_id == run.id).first()
        if fresh is None:
            raise
        fresh.status = "generation_failed"
        fresh.error_code = "generation_error"
        fresh.error_summary = str(exc)[:400]
        db.commit()
        db.refresh(fresh)
        return fresh


def reap_stale_generating(db: Session, older_than_s: int = 600) -> int:
    """陈旧 generating 收割：有完整子 run 幂等重算；无证据标失败。"""
    from datetime import timedelta
    cutoff = utcnow() - timedelta(seconds=older_than_s)
    stale = db.query(ScenarioReport).filter(
        ScenarioReport.status == "generating",
        ScenarioReport.created_at < cutoff).all()
    n = 0
    for rep in stale:
        run = db.get(ScenarioRun, rep.scenario_run_id)
        if run is None:
            continue
        generate_report(db, run)
        n += 1
    return n
