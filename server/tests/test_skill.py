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
