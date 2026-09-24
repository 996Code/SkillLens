"""Task 5 演示基线固化：/api/v1/baseline/skills* 字段与通过率计算（C2 对比锚）。"""
import json

from app.db import SessionLocal
from app.models import ReplayRun


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    """参考 test_replay_api._seed_skill：两 session 输入值不同 → 有 input_variables。"""
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


def _add_replay_run(skill_id: int, assertion_results) -> int:
    """直接落 replay_run 行（API 层测试不依赖回放浏览器链路）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(skill_id=skill_id, mode="execute", status="execute",
                        plan={"url": "http://t/f", "steps": []}, executed=[],
                        assertion_results=assertion_results)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_baseline_list_fields(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [{"passed": True}, {"passed": False}, {"passed": True}])

    resp = await client.get("/api/v1/baseline/skills")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list) and len(items) == 1
    item = items[0]
    assert item["skill_id"] == skill_id
    assert item["name"] == "SaveForm"
    assert item["status"] == "learned"
    assert item["confidence"] == 1.0            # api 步 0.6 + 有输入变量 0.4
    assert item["evidence_count"] == 2
    n_assertions = len((await client.get(f"/api/v1/skills/{skill_id}/assertions")).json())
    assert n_assertions >= 2                   # 至少 2 条 api_status（每 session 1 条）
    assert item["assertion_count"] == n_assertions
    assert item["assertion_pass_rate"] == round(2 / 3, 4)   # 最近 run：3 断言 2 过
    assert item["input_var_names"] == ["请输入"]
    assert item["window_params"] == {"idle_ms": 2000, "max_window_ms": 8000,
                                     "consistent": True}


async def test_baseline_pass_rate_uses_latest_run(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [{"passed": True}, {"passed": True}])        # 旧 run 全过
    _add_replay_run(skill_id, [{"passed": False}, {"passed": False}])      # 新 run 全挂
    item = (await client.get("/api/v1/baseline/skills")).json()[0]
    assert item["assertion_pass_rate"] == 0.0


async def test_baseline_no_run_pass_rate_null(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, None)   # shadow run（assertion_results 为 NULL）不算
    item = (await client.get("/api/v1/baseline/skills")).json()[0]
    assert item["assertion_count"] >= 2
    assert item["assertion_pass_rate"] is None


async def test_baseline_single_skill_and_404(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    resp = await client.get(f"/api/v1/baseline/skills/{skill_id}")
    assert resp.status_code == 200
    item = resp.json()
    assert item["skill_id"] == skill_id
    assert set(item) == {"skill_id", "name", "status", "confidence",
                         "evidence_count", "assertion_count", "assertion_pass_rate",
                         "input_var_names", "window_params"}

    assert (await client.get("/api/v1/baseline/skills/99999")).status_code == 404
