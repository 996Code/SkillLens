"""S13 Task 2（F2）：Impact Analysis——evidence_edge 图遍历 + 端点。

- induce 真管道造 evidence_edge（contains: session→click:保存 / calls: click:保存→POST:/a/{id}/save）
  → 变更集含已知 api 模板 → affected_skills 命中且 paths 非空；
- 无关模板 → 空 affected；两项全缺 → 422；
- GET /impact/last → 最近一次 nightly agent_run 输入输出。
"""
import json


async def _seed_skill(client, monkeypatch) -> dict:
    """FakeProvider 真管道：induce 产生 skill + evidence_edge（calls/contains）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    return (await client.post(f"/api/v1/alignments/{aid}/induce")).json()


async def test_analyze_api_template_hits_skill(client, monkeypatch):
    skill = await _seed_skill(client, monkeypatch)
    resp = await client.post("/api/v1/impact/analyze",
                             json={"api_templates": ["POST:/a/{id}/save"]})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["affected_skills"]) == 1
    hit = body["affected_skills"][0]
    assert hit["skill_id"] == skill["id"]
    assert hit["name"] == "SaveForm"
    assert hit["confidence"] == skill["confidence"]
    assert hit["paths"], "影响路径必须非空"
    path = hit["paths"][0]
    assert "api:POST:/a/{id}/save" in path          # api 模板起点
    assert "action:click:保存" in path               # calls 边反查到的 action
    assert f"skill:{skill['id']}" in path            # 终点 skill
    assert body["total_skills"] == 1
    assert body["unchanged_count"] == 0


async def test_analyze_anchor_label_hits_skill(client, monkeypatch):
    skill = await _seed_skill(client, monkeypatch)
    resp = await client.post("/api/v1/impact/analyze",
                             json={"anchor_labels": ["click:保存"]})
    assert resp.status_code == 200
    body = resp.json()
    assert [s["skill_id"] for s in body["affected_skills"]] == [skill["id"]]
    assert body["affected_skills"][0]["paths"]


async def test_analyze_unrelated_template_empty(client, monkeypatch):
    await _seed_skill(client, monkeypatch)
    resp = await client.post("/api/v1/impact/analyze",
                             json={"api_templates": ["/nope/{id}/x"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["affected_skills"] == []
    assert body["total_skills"] == 1
    assert body["unchanged_count"] == 1


async def test_analyze_requires_at_least_one(client):
    resp = await client.post("/api/v1/impact/analyze", json={})
    assert resp.status_code == 422


async def test_impact_last_nightly_run(client, monkeypatch):
    skill = await _seed_skill(client, monkeypatch)
    # 无 nightly 运行 → 404
    assert (await client.get("/api/v1/impact/last")).status_code == 404

    from app.agents.runtime import run_graph
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        await run_graph(db, "nightly",
                        {"change_set": {"api_templates": ["POST:/a/{id}/save"]}})
    finally:
        db.close()

    resp = await client.get("/api/v1/impact/last")
    assert resp.status_code == 200
    body = resp.json()
    assert body["graph_name"] == "nightly"
    assert body["status"] == "finished"
    assert body["input"]["change_set"]["api_templates"] == ["POST:/a/{id}/save"]
    nodes = [seg["node"] for seg in body["node_outputs"]]
    assert nodes == ["select_skills", "replay_batch", "aggregate"]
    assert body["node_outputs"][0]["output"]["skills"] == [skill["id"]]
