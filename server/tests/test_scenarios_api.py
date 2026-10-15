"""AR1 Scenario 身份收敛契约测试。"""
from datetime import timedelta
import hashlib
import secrets

import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, Skill


@pytest.fixture
def scenario_client(client: AsyncClient):
    yield client


def _mk_skill(name: str = "场景测试技能") -> int:
    db = SessionLocal()
    try:
        al = Alignment(session_ids=[], skeleton=[], buckets=[], input_variables=[],
                       param_variables=[], window_params={})
        db.add(al)
        db.flush()
        skill = Skill(alignment_id=al.id, name=name, description="用户保存表单",
                      status="learned", skeleton=[], param_variables=[],
                      input_variables=[], confidence=0.9, evidence_count=1)
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return skill.id
    finally:
        db.close()


async def test_scenario_crud_version_and_archive(scenario_client):
    skill_id = _mk_skill()
    created = await scenario_client.post("/api/v1/scenarios", json={
        "name": "JeecG 保存表单",
        "system": "JeecG 表单",
        "steps": [{"skill_id": skill_id, "overrides": {}}],
    })
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "active"
    assert body["definition_version"] == 1
    assert body["origin"] == "manual"
    scenario_id = body["id"]

    listed = (await scenario_client.get("/api/v1/scenarios?status=active")).json()
    assert any(row["id"] == scenario_id for row in listed)

    missing_precondition = await scenario_client.patch(
        f"/api/v1/scenarios/{scenario_id}", json={
            "name": "v2", "system": "JeecG 表单",
            "steps": [{"skill_id": skill_id, "overrides": {}}],
        })
    assert missing_precondition.status_code == 428

    stale = await scenario_client.patch(
        f"/api/v1/scenarios/{scenario_id}", headers={"If-Match": "99"}, json={
            "name": "v2", "system": "JeecG 表单",
            "steps": [{"skill_id": skill_id, "overrides": {}}],
        })
    assert stale.status_code == 409

    updated = await scenario_client.patch(
        f"/api/v1/scenarios/{scenario_id}", headers={"If-Match": "1"}, json={
            "name": "JeecG 保存表单 v2", "system": "JeecG 表单",
            "steps": [{"skill_id": skill_id, "overrides": {"name": "新值"}}],
        })
    assert updated.status_code == 200, updated.text
    assert updated.json()["definition_version"] == 2

    archived = await scenario_client.post(f"/api/v1/scenarios/{scenario_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert (await scenario_client.get(f"/api/v1/scenarios/{scenario_id}")).status_code == 200


async def test_scenario_nested_reference_uses_scenario_id(scenario_client):
    skill_id = _mk_skill("子场景技能")
    child = (await scenario_client.post("/api/v1/scenarios", json={
        "name": "子场景", "system": "JeecG 表单",
        "steps": [{"skill_id": skill_id, "overrides": {}}],
    })).json()
    parent = await scenario_client.post("/api/v1/scenarios", json={
        "name": "父场景", "system": "JeecG 表单",
        "steps": [{"scenario_id": child["id"], "overrides": {}}],
    })
    assert parent.status_code == 201, parent.text
    detail = (await scenario_client.get(
        f"/api/v1/scenarios/{parent.json()['id']}")).json()
    assert detail["steps"][0]["scenario_id"] == child["id"]
    assert "chain_id" not in detail["steps"][0]


async def test_old_chain_api_is_gone(scenario_client):
    response = await scenario_client.get("/api/v1/chains")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


async def test_scenario_role_gates(scenario_client):
    skill_id = _mk_skill("角色场景技能")
    from app.api.auth import hash_password
    from app.models import AuthToken, User, utcnow

    db = SessionLocal()
    try:
        user = User(username="ar1-viewer", role="viewer",
                    password_hash=hash_password("pw-ar1-viewer"))
        db.add(user)
        db.flush()
        raw = secrets.token_urlsafe(24)
        db.add(AuthToken(user_id=user.id,
                         token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                         expires_at=utcnow() + timedelta(days=1)))
        db.commit()
    finally:
        db.close()

    headers = {"Authorization": f"Bearer {raw}"}
    response = await scenario_client.post("/api/v1/scenarios", headers=headers, json={
        "name": "viewer 场景", "system": "x",
        "steps": [{"skill_id": skill_id, "overrides": {}}],
    })
    assert response.status_code == 403
    assert (await scenario_client.get("/api/v1/scenarios", headers=headers)).status_code == 200


async def test_legacy_suite_writes_are_frozen(scenario_client):
    assert (await scenario_client.post("/api/v1/suites", json={
        "name": "旧套件", "skill_ids": [1],
    })).status_code == 410
    assert (await scenario_client.post(
        "/api/v1/suites/1/run", json={"confirm_side_effect": False})).status_code == 410
    assert (await scenario_client.delete("/api/v1/suites/1")).status_code == 410


async def test_legacy_report_and_review_writes_are_frozen(scenario_client):
    report = await scenario_client.post(
        "/api/v1/expected-deltas/1/report", json={"observed_delta_id": 1})
    assert report.status_code == 410
    review = await scenario_client.post("/api/v1/reviews", json={
        "agent_run_id": 1, "decision": "approved"})
    assert review.status_code == 410
