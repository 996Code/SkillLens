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


async def test_induce_writes_strategies_and_evidence(client, monkeypatch):
    """T3+T4：induce 落 SkillStrategy（分桶数）与 evidence_edge（contains/calls 幂等累加）。"""
    import json as _json
    from app.db import SessionLocal
    from app.models import EvidenceEdge, SkillStrategy
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _json.dumps({"name": "S", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = []
    for i, note in enumerate(("a", "b")):
        ev += [
            {"seq": i*2, "ts": i*200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": i*2+1, "ts": i*200+100, "kind": "network",
             "payload": {"method": "POST", "url": "/orders/1/save", "status": 200,
                         "reqBody": _json.dumps({"note": note}), "resBody": '{"code":200}'}},
        ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    await client.post(f"/api/v1/sessions/{sid}/process")
    sid2 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    await client.post(f"/api/v1/sessions/{sid2}/events", json=ev)
    await client.post(f"/api/v1/sessions/{sid2}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid2]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    db = SessionLocal()
    try:
        strategies = db.query(SkillStrategy).filter(SkillStrategy.skill_id == skill["id"]).all()
        assert len(strategies) == 1  # 同签名 → 1 桶
        assert strategies[0].evidence_count == 2
        assert "click:保存" in strategies[0].strategy_signature

        edges = db.query(EvidenceEdge).filter(EvidenceEdge.dst == "click:保存").all()
        assert edges and all(e.type == "contains" for e in edges)
        calls = db.query(EvidenceEdge).filter(EvidenceEdge.src == "click:保存").all()
        assert calls and all(e.type == "calls" for e in calls)
        # 二次 induce：策略行重建、边幂等累加（计数≥2，不重复建行）
        await client.post(f"/api/v1/alignments/{aid}/induce")
        n_edges_before = db.query(EvidenceEdge).count()
        strategies2 = db.query(SkillStrategy).filter(
            SkillStrategy.skill_id == skill["id"]).all()
        assert len(strategies2) == 1
        await client.post(f"/api/v1/alignments/{aid}/induce")
        n_edges_after = db.query(EvidenceEdge).count()
        assert n_edges_after == n_edges_before  # 行数不增（幂等）
        call_edge = db.query(EvidenceEdge).filter(
            EvidenceEdge.src == "click:保存", EvidenceEdge.type == "calls").first()
        assert call_edge.evidence_count >= 2  # 每 induce 累加（signature 可编码多个 api 调用）
    finally:
        db.close()


async def test_list_skills_source_field(client, monkeypatch):
    """S10 Task5：GET /skills 列表项带 source（首个 session 来源，缺省 demo）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormConfig", "description": "保存"}))

    async def _make(source):
        sids = []
        for order_id in (111, 222):
            body = {"source": source} if source else {}
            sid = (await client.post("/api/v1/sessions", json=body)).json()["session_id"]
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
        aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
        return (await client.post(f"/api/v1/alignments/{aid}/induce")).json()["id"]

    demo_skill = await _make(None)
    real_skill = await _make("real_traffic")

    skills = (await client.get("/api/v1/skills")).json()
    by_id = {s["id"]: s for s in skills}
    assert by_id[demo_skill]["source"] == "demo"
    assert by_id[real_skill]["source"] == "real_traffic"
