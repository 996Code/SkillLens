"""S25 块 W T1：expected_delta.external_ref 需求条目关联（TDD 先红）。

- 创建时可带 external_ref（Jira key 等）；GET 透出；
- 报告响应（需求上下文数据源）透出；缺省为 null 不影响存量。
"""
import json


async def _seed_confirmed_delta(client, monkeypatch, external_ref=None) -> dict:
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://mock.local/"}},
        {"seq": 1, "ts": 100, "kind": "action", "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action", "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network", "payload": {"method": "POST", "url": "/a/1/save", "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    body = {"requirement_id": "s25-ref", "requirement_text": "测试"}
    if external_ref is not None:
        body["external_ref"] = external_ref
    delta = (await client.post("/api/v1/expected-deltas", json=body)).json()
    delta = (await client.post(f"/api/v1/expected-deltas/{delta['id']}/confirm",
                              json={"reviewed_by": "s25",
                                    "changes": [{"type": "api_add",
                                                 "value": "/a/1/save"}]})).json()
    return {"skill": skill, "delta": delta}


async def test_external_ref_stored_and_exposed(client, monkeypatch):
    seeded = await _seed_confirmed_delta(client, monkeypatch, external_ref="PROJ-123")
    delta_id = seeded["delta"]["id"]

    resp = await client.get(f"/api/v1/expected-deltas/{delta_id}")
    assert resp.status_code == 200
    assert resp.json()["external_ref"] == "PROJ-123"


async def test_external_ref_optional(client, monkeypatch):
    """缺省 null——存量行为不变。"""
    seeded = await _seed_confirmed_delta(client, monkeypatch)
    resp = await client.get(f"/api/v1/expected-deltas/{seeded['delta']['id']}")
    assert resp.json()["external_ref"] is None
