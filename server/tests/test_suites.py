"""AR1 legacy Suite is read-only until ScenarioRun cutover."""
import json


async def _seed_skill(client, monkeypatch, name="SuiteFlow") -> int:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": name, "description": "d"}))
    session_id = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 2, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{session_id}/events", json=events)
    await client.post(f"/api/v1/sessions/{session_id}/process")
    alignment_id = (await client.post(
        "/api/v1/align", json={"session_ids": [session_id, session_id]}
    )).json()["alignment_id"]
    skill = (await client.post(
        f"/api/v1/alignments/{alignment_id}/induce"
    )).json()
    return skill["id"]


async def test_suite_write_endpoints_are_gone(client):
    assert (await client.post("/api/v1/suites", json={
        "name": "旧套件", "skill_ids": [1]})).status_code == 410
    assert (await client.delete("/api/v1/suites/1")).status_code == 410
    assert (await client.post("/api/v1/suites/1/run", json={
        "confirm_side_effect": False})).status_code == 410


async def test_legacy_suite_remains_readable_with_migration_decision(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import TestSuite

    skill_id = await _seed_skill(client, monkeypatch)
    db = SessionLocal()
    try:
        suite = TestSuite(
            name="历史混合套件", skill_ids=[skill_id], canvas_id=None,
            scenario_id=None, migration_status="legacy_mixed_system",
            migration_reason="混合系统套件：ERPNext 客户、Odoo 销售",
        )
        db.add(suite)
        db.commit()
        db.refresh(suite)
        suite_id = suite.id
    finally:
        db.close()

    rows = (await client.get("/api/v1/suites")).json()
    item = next(row for row in rows if row["id"] == suite_id)
    assert item["scenario_id"] is None
    assert item["migration_status"] == "legacy_mixed_system"
    assert "混合系统" in item["migration_reason"]
    assert item["skills"][0]["id"] == skill_id

    detail = (await client.get(f"/api/v1/suites/{suite_id}")).json()
    assert detail["migration_status"] == "legacy_mixed_system"


async def test_legacy_suite_run_history_remains_readable(client):
    from app.db import SessionLocal
    from app.models import SuiteRun, TestSuite

    db = SessionLocal()
    try:
        suite = TestSuite(
            name="历史套件", skill_ids=[], canvas_id=None,
            scenario_id=None, migration_status="legacy_unknown_system",
            migration_reason="技能系统无法确定",
        )
        db.add(suite)
        db.flush()
        run = SuiteRun(
            suite_id=suite.id, results=[], total=0, pass_count=0,
            fail_count=0, error_count=0, shadow_count=0, agent_run_id=None,
        )
        db.add(run)
        db.commit()
        suite_id = suite.id
        run_id = run.id
    finally:
        db.close()

    rows = (await client.get(f"/api/v1/suites/{suite_id}/runs")).json()
    assert rows[0]["id"] == run_id
