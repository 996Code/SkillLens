import json
import os

import pytest


@pytest.fixture
def fake_llm(monkeypatch):
    os.environ.pop("LLM_API_KEY", None)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormConfig", "description": "保存表单配置"}))


async def _make_alignment(client) -> int:
    sids = []
    for order_id in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 2000, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 2600, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    resp = await client.post("/api/v1/align", json={"session_ids": sids})
    return resp.json()["alignment_id"]


async def test_induce_learned(client, fake_llm):
    aid = await _make_alignment(client)
    resp = await client.post(f"/api/v1/alignments/{aid}/induce")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "SaveFormConfig"
    assert body["status"] == "learned"
    assert body["evidence_count"] == 2
    assert 0 < body["confidence"] <= 1
    assert len(body["skeleton"]) == 1


async def test_induce_candidate_on_bad_json(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "not-json")
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert body["name"] == "Candidate"
    assert "解析" in body["notes"] or "JSON" in body["notes"]


async def test_induce_candidate_on_bad_name(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "save form", "description": "x"}))
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert "PascalCase" in body["notes"]


async def test_induce_idempotent(client, fake_llm):
    aid = await _make_alignment(client)
    await client.post(f"/api/v1/alignments/{aid}/induce")
    await client.post(f"/api/v1/alignments/{aid}/induce")
    skills = (await client.get("/api/v1/skills")).json()
    assert len([s for s in skills if s["alignment_id"] == aid]) == 1


async def test_reinduce_removes_old_assertions(client, fake_llm):
    # re-induce 删旧 Skill 前必须先删其断言：否则旧行 skill_id 悬空，verify 500
    aid = await _make_alignment(client)
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill['id']}/assertions")).json()
    assert rows
    old_ids = [r["id"] for r in rows]

    await client.post(f"/api/v1/alignments/{aid}/induce")

    from app.db import SessionLocal
    from app.models import OutcomeAssertion
    db = SessionLocal()
    try:
        for oid in old_ids:
            assert db.get(OutcomeAssertion, oid) is None  # 旧断言行已删除
    finally:
        db.close()

    for oid in old_ids:
        resp = await client.post(f"/api/v1/assertions/{oid}/verify")
        assert resp.status_code == 404                    # 404，而非孤儿 500


async def test_verify_assertion_missing_skill_404(client):
    # 兜底：断言存在但 skill 已消失（历史孤儿数据）→ 404 而非 AttributeError 500
    from app.db import SessionLocal
    from app.models import OutcomeAssertion
    db = SessionLocal()
    orphan = OutcomeAssertion(skill_id=999999, layer=3, kind="api_status",
                              api_template="/x/y", payload={})
    db.add(orphan)
    db.commit()
    orphan_id = orphan.id
    db.close()

    resp = await client.post(f"/api/v1/assertions/{orphan_id}/verify")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "skill not found"
