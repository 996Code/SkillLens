import json


async def _make_learned_skill(client, monkeypatch) -> tuple[int, str]:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveOrder", "description": "保存订单"}))
    sids = []
    for oid in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 100, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 300, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": json.dumps({"note": f"n{oid}"}),
                         "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        await client.post(f"/api/v1/sessions/{sid}/field-changes")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"], sids[0]


async def test_generate_assertions(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    resp = await client.post(f"/api/v1/skills/{skill_id}/assertions")
    assert resp.status_code == 200
    n = resp.json()["assertions"]
    assert n >= 3  # api_status + state_signal + field_change
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"api_status", "state_signal", "field_change"}


async def test_verify_all_pass(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    for r in rows:
        result = (await client.post(f"/api/v1/assertions/{r['id']}/verify")).json()
        assert result["passed"] is True, r


async def test_verify_detects_failure(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    # 直接改库造一个失败：删除第一个 session 的 field_change
    from app.db import SessionLocal
    from app.models import FieldChange
    db = SessionLocal()
    db.query(FieldChange).filter(FieldChange.session_id ==
                                 (await _first_alignment_session(client, skill_id))).delete()
    db.commit()
    db.close()
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    fc = next(r for r in rows if r["kind"] == "field_change")
    result = (await client.post(f"/api/v1/assertions/{fc['id']}/verify")).json()
    assert result["passed"] is False


async def _first_alignment_session(client, skill_id):
    from app.db import SessionLocal
    from app.models import Alignment, Skill
    db = SessionLocal()
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    db.close()
    return alignment.session_ids[0]
