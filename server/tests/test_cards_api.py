"""Task 1（S9 块C）：GET /api/v1/skills/{id}/card 聚合端点——骨架+变量+断言+最近 run 概要。"""
import json

from app.db import SessionLocal
from app.models import ReplayRun


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    """参考 test_baseline_api._seed_skill：两 session 输入值不同 → 有 input_variables。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
    sids = []
    for value in ("旧甲", "旧乙"):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
            {"seq": 1, "ts": 100, "kind": "action",
             "payload": {"type": "input", "name": "请输入", "value": value}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 260, "kind": "network",
             "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                         "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


def _add_replay_run(skill_id: int, assertion_results, mode="execute", status="execute") -> int:
    """直接落 replay_run 行（API 层测试不依赖回放浏览器链路）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(skill_id=skill_id, mode=mode, status=status,
                        plan={"url": "http://t/f", "steps": []}, executed=[],
                        assertion_results=assertion_results)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_card_full_fields(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, None, mode="shadow", status="pass")   # 更早的 shadow run
    run_id = _add_replay_run(skill_id, [{"passed": True}, {"passed": False}])

    resp = await client.get(f"/api/v1/skills/{skill_id}/card")
    assert resp.status_code == 200
    card = resp.json()
    assert set(card) == {"id", "name", "description", "status", "confidence",
                         "evidence_count", "alignment_id", "skeleton", "input_variables",
                         "param_variables", "assertions", "strategies", "last_run", "window_params",
                         "notes"}
    assert card["id"] == skill_id
    assert card["name"] == "SaveForm"
    assert card["status"] == "learned"
    assert card["confidence"] == 1.0            # api 步 0.6 + 有输入变量 0.4
    assert card["evidence_count"] == 2
    assert card["alignment_id"] > 0
    assert isinstance(card["skeleton"], list) and card["skeleton"]
    assert isinstance(card["input_variables"], list) and card["input_variables"]
    assert card["input_variables"][0]["name"] == "请输入"
    assert set(card["input_variables"][0]["values"].values()) == {"旧甲", "旧乙"}
    # skeleton 结构透传（align 端点同源），param_variables 同为列表
    align = (await client.get(f"/api/v1/alignments/{card['alignment_id']}")).json()
    assert card["skeleton"] == align["skeleton"]
    assert card["param_variables"] == align["param_variables"]
    # 断言行：id/kind/layer/payload
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    assert len(card["assertions"]) == len(rows)
    for a, r in zip(card["assertions"], rows):
        assert set(a) == {"id", "kind", "layer", "payload"}
        assert a["id"] == r["id"] and a["kind"] == r["kind"] and a["layer"] == r["layer"]
        assert a["payload"] == r["payload"]
    # last_run：取 id 倒序第一条（shadow 也算）
    assert card["last_run"] == {"id": run_id, "status": "execute", "mode": "execute",
                                "ts": card["last_run"]["ts"]}
    # window_params 从 alignment 读
    assert card["window_params"] == {"idle_ms": 2000, "max_window_ms": 8000,
                                     "consistent": True}


async def test_card_without_run_last_run_null(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch, llm_name="NoRun")
    card = (await client.get(f"/api/v1/skills/{skill_id}/card")).json()
    assert card["last_run"] is None
    assert card["assertions"]   # 断言仍聚合


async def test_card_404(client):
    assert (await client.get("/api/v1/skills/99999/card")).status_code == 404
