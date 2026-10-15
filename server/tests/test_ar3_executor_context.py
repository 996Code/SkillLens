"""AR3 executor protocol scenario context tests."""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, Scenario, ScenarioRun, Skill


async def _seed(db, name="AR3 技能") -> int:
    import uuid
    from app.models import RawEvent
    ref = f"ar3-ref-{uuid.uuid4().hex[:8]}"
    al = Alignment(session_ids=[ref], skeleton=[],
                   buckets=[], input_variables=[], param_variables=[],
                   window_params={})
    db.add(al)
    db.flush()
    db.add(RawEvent(session_id=ref, seq=0, ts=0, kind="navigation",
                    payload={"type": "page-load", "url": "http://t/ar3"}))
    sk = Skill(alignment_id=al.id, name=name, description="d", status="learned",
               skeleton=[{"signature": "POST:/x/save"}], param_variables=[],
               input_variables=[], confidence=0.9, evidence_count=1)
    db.add(sk)
    db.commit()
    db.refresh(sk)
    return sk.id


def _closure(scenario_id: int, sid: int) -> dict:
    return {"root": {"scenario_id": scenario_id, "definition_version": 1},
            "steps": [{"execution_index": 0, "skill_id": sid,
                       "source_path": [{"scenario_id": scenario_id,
                                        "local_index": 0, "version": 1}],
                       "step": {"skill_id": sid, "overrides": {}}}]}


async def test_step_must_belong_to_scenario_snapshot(client: AsyncClient):
    """plan 带 scenario_run_id 时：skill 必须在闭包快照内且 execution_index 匹配。"""
    db = SessionLocal()
    try:
        sid = await _seed(db, "快照内技能")
        other = await _seed(db, "快照外技能")
        sc = Scenario(name="AR3 场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        run = ScenarioRun(scenario_id=sc.id, definition_version=1,
                          definition_snapshot=_closure(sc.id, sid),
                          executor="extension", mode="execute", status="running",
                          confirm_side_effect=True,
                          idempotency_key="ar3-snap-1",
                          request_fingerprint="f" * 64)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        sc_id = sc.id
        sid_in, sid_out = sid, other
    finally:
        db.close()

    # 快照外技能 → 409（不允许任意挂靠）
    r1 = await client.post("/api/v1/executor/skills/%d/plan" % sid_out, json={
        "overrides": {}, "confirm_side_effect": True,
        "scenario_run_id": run_id, "execution_index": 0})
    assert r1.status_code == 409, r1.text

    # execution_index 越界 → 409
    r2 = await client.post("/api/v1/executor/skills/%d/plan" % sid_in, json={
        "overrides": {}, "confirm_side_effect": True,
        "scenario_run_id": run_id, "execution_index": 5})
    assert r2.status_code == 409

    # 快照内且索引正确 → 200（shadow 短路因 confirm=True 且骨架写→不短路路径；
    # 挂归属后返回）
    r3 = await client.post("/api/v1/executor/skills/%d/plan" % sid_in, json={
        "overrides": {}, "confirm_side_effect": True,
        "scenario_run_id": run_id, "execution_index": 0})
    assert r3.status_code == 200, r3.text

    db = SessionLocal()
    try:
        from app.models import ReplayRun
        rr = db.query(ReplayRun).filter(
            ReplayRun.scenario_run_id == run_id).first()
        assert rr is not None, "子 run 必须挂上归属列"
        assert rr.execution_index == 0
        assert rr.scope_kind == "scenario"
    finally:
        db.close()


async def test_child_cannot_override_parent_confirm_or_source(client: AsyncClient):
    """父运行锁定 C1：confirm=False 的父下，子 plan 传 confirm=True 被拒（409）。

    语义：confirm 与 source_track/executor 只能从父 ScenarioRun 读——插件
    不得用客户端值覆盖 C1/C2（当前插件固定发 confirm=true，若无此闸，
    shadow 场景会被插件当 execute 跑）。
    """
    db = SessionLocal()
    try:
        sid = await _seed(db, "C1 父锁技能")
        sc = Scenario(name="C1 父锁场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        run = ScenarioRun(scenario_id=sc.id, definition_version=1,
                          definition_snapshot=_closure(sc.id, sid),
                          executor="extension", mode="shadow", status="running",
                          confirm_side_effect=False,  # 父定格 shadow
                          idempotency_key="ar3-c1-1",
                          request_fingerprint="f" * 64)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        sid_locked = sid
    finally:
        db.close()

    r = await client.post("/api/v1/executor/skills/%d/plan" % sid_locked, json={
        "overrides": {}, "confirm_side_effect": True,  # 与父冲突
        "scenario_run_id": run_id, "execution_index": 0})
    assert r.status_code == 409
    assert "C1" in r.json().get("detail", "") or "confirm" in r.json().get("detail", "").lower()


async def test_finish_scenario_run_is_idempotent(client: AsyncClient):
    db = SessionLocal()
    try:
        sid = await _seed(db, "finish 技能")
        sc = Scenario(name="finish 场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        run = ScenarioRun(scenario_id=sc.id, definition_version=1,
                          definition_snapshot=_closure(sc.id, sid),
                          executor="extension", mode="execute", status="running",
                          confirm_side_effect=True,
                          idempotency_key="ar3-fin-1",
                          request_fingerprint="f" * 64)
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    r1 = await client.post(f"/api/v1/scenario-runs/{run_id}/finish",
                           json={"status": "pass"})
    assert r1.status_code == 200
    r2 = await client.post(f"/api/v1/scenario-runs/{run_id}/finish",
                           json={"status": "pass"})
    assert r2.status_code == 200, "相同终态幂等"
    r3 = await client.post(f"/api/v1/scenario-runs/{run_id}/finish",
                           json={"status": "fail"})
    assert r3.status_code == 409, "冲突终态拒绝"
