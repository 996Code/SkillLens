"""AR2 ScenarioRun 服务端聚合契约测试（规格 §AR2 RED 清单）。"""
import hashlib
import json
from typing import Any

import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, ReplayRun, Scenario, Skill


async def _seed(db, name: str = "AR2 技能") -> int:
    al = Alignment(session_ids=[], skeleton=[], buckets=[], input_variables=[],
                   param_variables=[], window_params={})
    db.add(al)
    db.flush()
    sk = Skill(alignment_id=al.id, name=name, description="d", status="learned",
               skeleton=[], param_variables=[], input_variables=[],
               confidence=0.9, evidence_count=1)
    db.add(sk)
    db.commit()
    db.refresh(sk)
    return sk.id


def _body(skill_id: int, **extra) -> dict:
    return {"executor": "server", "confirm_side_effect": True,
            "steps": [{"skill_id": skill_id, "overrides": {}}], **extra}


def _key(n: str) -> dict:
    return {"Idempotency-Key": n}


@pytest.fixture
def srun_client(client: AsyncClient):
    yield client


async def test_start_is_idempotent(srun_client):
    db = SessionLocal()
    try:
        sid = await _seed(db, "幂等技能")
        sc = Scenario(name="幂等场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        body = _body(sid)
        r1 = await srun_client.post(f"/api/v1/scenarios/{sc.id}/runs",
                                    headers=_key("idem-1"), json=body)
        assert r1.status_code in (200, 201), r1.text
        rid = r1.json()["id"]
        r2 = await srun_client.post(f"/api/v1/scenarios/{sc.id}/runs",
                                    headers=_key("idem-1"), json=body)
        assert r2.status_code == r1.status_code
        assert r2.json()["id"] == rid
    finally:
        db.close()


async def test_same_key_different_body_conflicts(srun_client):
    db = SessionLocal()
    try:
        sid = await _seed(db, "冲突技能")
        sc = Scenario(name="冲突场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        r1 = await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("conflict-1"),
            json=_body(sid, confirm_side_effect=True))
        assert r1.status_code in (200, 201)
        r2 = await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("conflict-1"),
            json=_body(sid, confirm_side_effect=False))
        assert r2.status_code == 409
    finally:
        db.close()


async def test_nested_snapshot_keeps_source_path_and_child_version(srun_client):
    db = SessionLocal()
    try:
        sid = await _seed(db, "嵌套技能")
        child = Scenario(name="子场景", system="x", definition_version=7,
                         steps=[{"skill_id": sid, "overrides": {}}])
        db.add(child)
        db.commit()
        db.refresh(child)
        parent = Scenario(name="父场景", system="x",
                          steps=[{"scenario_id": child.id, "overrides": {}}])
        db.add(parent)
        db.commit()
        db.refresh(parent)
        r = await srun_client.post(
            f"/api/v1/scenarios/{parent.id}/runs", headers=_key("nest-1"),
            json=_body(sid))
        assert r.status_code in (200, 201), r.text
        snap = r.json()["definition_snapshot"]
        assert snap["root"]["scenario_id"] == parent.id
        assert snap["steps"][0]["skill_id"] == sid
        assert snap["steps"][0]["source_path"] == [
            {"scenario_id": parent.id, "local_index": 0,
             "version": parent.definition_version},
            {"scenario_id": child.id, "local_index": 0, "version": 7},
        ]
    finally:
        db.close()


async def test_expectations_are_snapshotted_with_run(srun_client):
    """AR4 前置：expectation_snapshot 字段存在且初值为空列表（无绑定时）。"""
    db = SessionLocal()
    try:
        sid = await _seed(db, "期望技能")
        sc = Scenario(name="期望场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        r = await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("exp-1"),
            json=_body(sid))
        assert r.status_code in (200, 201)
        assert r.json()["expectation_snapshot"] == []
    finally:
        db.close()


async def test_repeated_subscenario_has_distinct_occurrence(srun_client):
    db = SessionLocal()
    try:
        sid = await _seed(db, "重复引用技能")
        child = Scenario(name="被引两次", system="x",
                         steps=[{"skill_id": sid, "overrides": {}}])
        db.add(child)
        db.commit()
        db.refresh(child)
        parent = Scenario(name="重复父", system="x", steps=[
            {"scenario_id": child.id, "overrides": {}},
            {"skill_id": sid, "overrides": {}},
            {"scenario_id": child.id, "overrides": {}},
        ])
        db.add(parent)
        db.commit()
        db.refresh(parent)
        r = await srun_client.post(
            f"/api/v1/scenarios/{parent.id}/runs", headers=_key("dup-1"),
            json=_body(sid))
        assert r.status_code in (200, 201), r.text
        snap = r.json()["definition_snapshot"]
        assert len(snap["steps"]) == 3
        paths = [s["source_path"] for s in snap["steps"]]
        assert paths[0] != paths[2], "同一子场景两次引用 occurrence 必须可区分"
        assert paths[0][1]["scenario_id"] == paths[2][1]["scenario_id"]
    finally:
        db.close()


async def test_c1_shadow_does_not_launch_browser(srun_client, monkeypatch):
    """C1：含写技能且未确认 → ScenarioRun 直接终态 shadow，不触执行器。"""
    from app.replay import runner as runner_mod
    from app.scenario import service as svc

    # service 层直接锁定：_skill_writes 命中 + confirm=False → shadow 短路
    called = []
    async def fake_replay(*a, **k):
        called.append(a)
        raise AssertionError("shadow 必须不触 run_replay")
    monkeypatch.setattr(runner_mod, "run_replay", fake_replay)

    db = SessionLocal()
    try:
        sid = await _seed(db, "写技能")
        # 构造含写动作骨架：requires_confirmation 对 click 提交类动作为真
        from app.models import Skill as SK
        sk = db.get(SK, sid)
        sk.skeleton = [{"kind": "api_status", "signature": "POST:/api/order/save"}]
        db.commit()
        sc = Scenario(name="C1 场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        assert svc._skill_writes(db, [{"skill_id": sid}]) is True

        r = await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("c1-1"),
            json=_body(sid, confirm_side_effect=False))
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body["status"] == "shadow"
        assert called == [], "C1 shadow 不得启动浏览器/执行器"
    finally:
        db.close()


async def test_blocked_step_creates_no_fake_replay_run(srun_client, monkeypatch):
    """业务步失败后，后续步骤 blocked——不落占位 ReplayRun。"""
    from app.replay import runner as runner_mod
    from app.models import ReplayRun as RR

    async def fake_replay(db, skill_id, ovr, confirm):
        if skill_id == FAIL_SKILL[0]:
            rr = RR(skill_id=skill_id, mode="execute", status="fail",
                    plan={"steps": []}, executed=None, assertion_results=None)
            db.add(rr); db.commit(); db.refresh(rr)
            return rr
        rr = RR(skill_id=skill_id, mode="execute", status="pass",
                plan={"steps": []}, executed=None, assertion_results=None)
        db.add(rr); db.commit(); db.refresh(rr)
        return rr

    db = SessionLocal()
    try:
        sid = await _seed(db, "blocked 首步")
        sid2 = await _seed(db, "blocked 后步")
        FAIL_SKILL.append(sid)
        sc = Scenario(name="blocked 场景", system="x", steps=[
            {"skill_id": sid, "overrides": {}},
            {"skill_id": sid2, "overrides": {}},
        ])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sc_id = sc.id
        before = db.query(RR).count()
    finally:
        db.close()

    monkeypatch.setattr(runner_mod, "run_replay", fake_replay)
    r = await srun_client.post(f"/api/v1/scenarios/{sc_id}/runs",
                               headers=_key("blk-1"), json=_body(sid))
    assert r.status_code in (200, 201), r.text
    body = r.json()
    assert body["status"] == "fail"
    assert body["blocked_count"] == 1
    assert body["pass_count"] + body["fail_count"] + body["error_count"] == 1

    db = SessionLocal()
    try:
        after = db.query(RR).count()
        assert after - before == 1, "blocked 步不得落占位 ReplayRun"
    finally:
        db.close()
    FAIL_SKILL.clear()


FAIL_SKILL: list[int] = []


async def test_terminal_state_is_immutable(srun_client):
    """终态后再 finish 冲突值 → 409；相同终态幂等。"""
    db = SessionLocal()
    try:
        sid = await _seed(db, "终态技能")
        sc = Scenario(name="终态场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        created = await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("term-1"),
            json={"executor": "server", "confirm_side_effect": False,
                  "steps": [{"skill_id": sid, "overrides": {}}],
                  "status": "pass"})
        assert created.status_code in (200, 201)
        rid = created.json()["id"]
        same = await srun_client.post(f"/api/v1/scenario-runs/{rid}/finish",
                                      json={"status": "pass"})
        assert same.status_code == 200
        conflict = await srun_client.post(f"/api/v1/scenario-runs/{rid}/finish",
                                          json={"status": "fail"})
        assert conflict.status_code == 409
    finally:
        db.close()


async def test_scenario_run_listing_and_detail(srun_client):
    db = SessionLocal()
    try:
        sid = await _seed(db, "列表技能")
        sc = Scenario(name="列表场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        created = (await srun_client.post(
            f"/api/v1/scenarios/{sc.id}/runs", headers=_key("list-1"),
            json=_body(sid))).json()
        lst = await srun_client.get(f"/api/v1/scenario-runs?scenario_id={sc.id}")
        assert lst.status_code == 200
        assert any(item["id"] == created["id"] for item in lst.json())
        detail = await srun_client.get(f"/api/v1/scenario-runs/{created['id']}")
        assert detail.status_code == 200
        assert detail.json()["scenario_id"] == sc.id
    finally:
        db.close()
