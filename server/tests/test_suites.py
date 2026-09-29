"""S37-3 测试套件（流水线打通）：操作流程组合 → 一键执行 → 汇总报告。

- POST /suites：创建（name + skill_ids）
- GET /suites：列表（含 skill 概要）
- GET /suites/{id}：详情
- DELETE /suites/{id}
- POST /suites/{id}/run：一键执行（逐操作流程自动测试，批级 C1 门控），
  返回套件级汇总（X 个操作 / Y 通过 / 失败明细 run_id）
- GET /suites/{id}/runs：执行历史
"""
import json


async def _seed_skill(client, monkeypatch, name="SuiteFlow") -> int:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": name, "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 2, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align",
                             json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"]


async def test_suite_crud(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post("/api/v1/suites", json={
        "name": "冒烟套件", "skill_ids": [skill_id]})
    assert r.status_code == 200, r.text
    suite = r.json()
    assert suite["name"] == "冒烟套件" and suite["skill_ids"] == [skill_id]

    rows = (await client.get("/api/v1/suites")).json()
    assert any(s["id"] == suite["id"] for s in rows)
    # 列表带 skill 概要
    target = next(s for s in rows if s["id"] == suite["id"])
    assert any(sk["id"] == skill_id for sk in target["skills"])

    detail = (await client.get(f"/api/v1/suites/{suite['id']}")).json()
    assert detail["name"] == "冒烟套件"

    r2 = await client.delete(f"/api/v1/suites/{suite['id']}")
    assert r2.status_code == 200
    assert (await client.get(f"/api/v1/suites/{suite['id']}")).status_code == 404


async def test_suite_validation(client, monkeypatch):
    r = await client.post("/api/v1/suites", json={"name": "", "skill_ids": []})
    assert r.status_code == 422
    r2 = await client.post("/api/v1/suites", json={"name": "x", "skill_ids": [99999]})
    assert r2.status_code == 422  # skill 不存在


async def test_suite_run_shadow(client, monkeypatch):
    """套件执行（shadow 模式：不确认副作用 → 各操作流程走预演门控）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    suite = (await client.post("/api/v1/suites", json={
        "name": "预演套件", "skill_ids": [skill_id]})).json()
    r = await client.post(f"/api/v1/suites/{suite['id']}/run",
                          json={"confirm_side_effect": False})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    assert body["results"][0]["skill_id"] == skill_id
    assert body["results"][0]["status"] == "shadow"
    assert "run_id" in body["results"][0]
    # 执行历史
    runs = (await client.get(f"/api/v1/suites/{suite['id']}/runs")).json()
    assert len(runs) >= 1
    assert runs[0]["total"] == 1
