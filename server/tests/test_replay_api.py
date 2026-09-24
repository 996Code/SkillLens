import json

import app.replay.runner as runner_mod


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
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
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


async def test_shadow_mode_without_confirmation(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fail_if_called(*a, **k):
        raise AssertionError("shadow mode must not launch browser")
    monkeypatch.setattr(runner_mod, "execute_plan", fail_if_called)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "shadow" and body["status"] == "shadow"
    assert body["executed"] is None and body["plan"]["steps"]  # 计划已编译落库


async def test_execute_mode_pass(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"code":200}'}]}

    class FakePage:
        async def goto(self, url): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
    class FakeBrowser:
        async def new_page(self): return FakePage()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    import app.replay.runner as rm
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())   # runner 内部浏览器入口（见实现）

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {"请输入": "新值"}, "confirm_side_effect": True})
    body = resp.json()
    assert body["mode"] == "execute" and body["status"] == "pass"
    assert body["plan"]["steps"][0]["value"] == "新值"       # override 注入
    assert all(r["passed"] for r in body["assertion_results"])


async def test_replay_run_get_404(client):
    resp = await client.get("/api/v1/replay-runs/9999")
    assert resp.status_code == 404
