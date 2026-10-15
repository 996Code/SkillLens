"""AR4 auto report + report review contract tests."""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import (Alignment, ExpectedDelta, RawEvent, Scenario,
                        ScenarioRun, Skill)


async def _seed(db, name="AR4 技能", sig="POST:/x/save") -> int:
    import uuid
    ref = f"ar4-ref-{uuid.uuid4().hex[:8]}"
    al = Alignment(session_ids=[ref], skeleton=[], buckets=[],
                   input_variables=[], param_variables=[], window_params={})
    db.add(al)
    db.flush()
    db.add(RawEvent(session_id=ref, seq=0, ts=0, kind="navigation",
                    payload={"type": "page-load", "url": "http://t/ar4"}))
    sk = Skill(alignment_id=al.id, name=name, description="d", status="learned",
               skeleton=[{"signature": sig}], param_variables=[],
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


async def _seed_confirmed_delta(client) -> int:
    import json as _json
    delta = (await client.post("/api/v1/expected-deltas", json={
        "requirement_id": f"ar4-req-{id(object())}", "requirement_text": "t"})).json()
    confirmed = (await client.post(
        f"/api/v1/expected-deltas/{delta['id']}/confirm",
        json={"reviewed_by": "ar4",
              "changes": [{"type": "api_add", "value": "/x/save"}]})).json()
    return confirmed["id"]


async def test_scenario_expectation_binding(client: AsyncClient):
    db = SessionLocal()
    try:
        sid = await _seed(db, "绑定技能")
        sc = Scenario(name="绑定场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sc_id = sc.id
    finally:
        db.close()
    delta_id = await _seed_confirmed_delta(client)

    r = await client.post(f"/api/v1/scenarios/{sc_id}/expectations", json={
        "expected_delta_id": delta_id, "step_index": None})
    assert r.status_code == 201, r.text
    assert r.json()["active"] is True

    # 重复绑定（同场景同期望同步索引）→ 409
    r2 = await client.post(f"/api/v1/scenarios/{sc_id}/expectations", json={
        "expected_delta_id": delta_id, "step_index": None})
    assert r2.status_code == 409

    # 列表
    lst = await client.get(f"/api/v1/scenarios/{sc_id}/expectations")
    assert lst.status_code == 200
    assert lst.json()[0]["expected_delta_id"] == delta_id


async def test_terminal_run_creates_exactly_one_report(client: AsyncClient):
    """终态 ScenarioRun → 自动生成一份 ScenarioReport。"""
    db = SessionLocal()
    try:
        sid = await _seed(db, "报告技能")
        sc = Scenario(name="报告场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sc_id = sc.id
    finally:
        db.close()
    delta_id = await _seed_confirmed_delta(client)
    await client.post(f"/api/v1/scenarios/{sc_id}/expectations", json={
        "expected_delta_id": delta_id, "step_index": None})

    created = (await client.post(f"/api/v1/scenarios/{sc_id}/runs",
                                 headers={"Idempotency-Key": "ar4-rep-1"},
                                 json={"executor": "server",
                                       "confirm_side_effect": True,
                                       "status": "pass"})).json()
    run_id = created["id"]

    r = await client.get(f"/api/v1/scenario-runs/{run_id}/report")
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["scenario_run_id"] == run_id
    assert rep["status"] == "ready"
    # 期望快照已定格进运行
    assert len(created["expectation_snapshot"]) == 1

    # 二次 finish（幂等重放）不产生第二份报告
    await client.post(f"/api/v1/scenario-runs/{run_id}/finish",
                      json={"status": "pass"})
    r2 = await client.get(f"/api/v1/scenario-runs/{run_id}/report")
    assert r2.json()["id"] == rep["id"]


async def test_no_expectation_is_ready_not_failed(client: AsyncClient):
    db = SessionLocal()
    try:
        sid = await _seed(db, "无期望技能", sig="GET:/x/query")
        sc = Scenario(name="无期望场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sc_id = sc.id
    finally:
        db.close()

    created = (await client.post(f"/api/v1/scenarios/{sc_id}/runs",
                                 headers={"Idempotency-Key": "ar4-noexp-1"},
                                 json={"executor": "server",
                                       "confirm_side_effect": True,
                                       "status": "pass"})).json()
    r = await client.get(f"/api/v1/scenario-runs/{created['id']}/report")
    assert r.status_code == 200
    rep = r.json()
    assert rep["status"] == "ready"
    assert rep["coverage_state"] == "no_expectation"


async def test_review_targets_report_and_is_immutable(client: AsyncClient):
    db = SessionLocal()
    try:
        sid = await _seed(db, "评审技能", sig="GET:/x/q2")
        sc = Scenario(name="评审场景", system="x",
                      steps=[{"skill_id": sid, "overrides": {}}])
        db.add(sc)
        db.commit()
        db.refresh(sc)
        sc_id = sc.id
    finally:
        db.close()

    created = (await client.post(f"/api/v1/scenarios/{sc_id}/runs",
                                 headers={"Idempotency-Key": "ar4-rev-1"},
                                 json={"executor": "server",
                                       "confirm_side_effect": True,
                                       "status": "pass"})).json()
    rep = (await client.get(
        f"/api/v1/scenario-runs/{created['id']}/report")).json()

    r1 = await client.post(f"/api/v1/reports/{rep['id']}/review", json={
        "decision": "approved", "comment": "全绿放行"})
    assert r1.status_code == 201, r1.text
    assert r1.json()["report_id"] == rep["id"]

    # 重复评审 → 409
    r2 = await client.post(f"/api/v1/reports/{rep['id']}/review", json={
        "decision": "rejected"})
    assert r2.status_code == 409

    # pending 队列只含 ready 且未评审
    pending = (await client.get("/api/v1/reviews/pending")).json()
    assert all(item["report_id"] != rep["id"] for item in pending)
