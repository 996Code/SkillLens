import json

import app.replay.runner as rm
from tests.test_replay_api import _seed_skill


async def test_fail_triggers_attribution(client, monkeypatch, tmp_path):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 500, "body": "err"}]}

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def screenshot(self, path): open(path, "w").write("png")
        async def title(self): return "测试页"
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())
    monkeypatch.setattr(rm, "ARTIFACT_DIR", str(tmp_path))

    captured = {}

    def fake_complete(db, purpose, prompt):
        captured["purpose"] = purpose
        captured["prompt"] = prompt
        class R: text = "接口 500，保存服务异常"
        return R()
    monkeypatch.setattr(rm, "complete", fake_complete)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    body = resp.json()
    assert body["status"] == "fail"
    assert "500" in body["attribution"] or "异常" in body["attribution"]
    assert captured["purpose"] == "replay_failure_attribution"
    assert body["artifact_path"].endswith(".png")


async def test_pass_no_attribution(client, monkeypatch, tmp_path):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"code":200}'}]}

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def screenshot(self, path): open(path, "w").write("png")
        async def title(self): return "测试页"
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())
    monkeypatch.setattr(rm, "ARTIFACT_DIR", str(tmp_path))

    def fail_complete(*a, **k):
        raise AssertionError("pass must not call LLM")
    monkeypatch.setattr(rm, "complete", fail_complete)

    body = (await client.post(f"/api/v1/skills/{skill_id}/replay",
                              json={"overrides": {}, "confirm_side_effect": True})).json()
    assert body["status"] == "pass" and body["attribution"] is None


async def test_execute_exception_lands_error_run(client, monkeypatch):
    """浏览器阶段异常也必须落 error run（C3：执行审计不可缺）。"""
    skill_id = await _seed_skill(client, monkeypatch)

    class FakePage:
        async def goto(self, url): raise RuntimeError("net reset")
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def screenshot(self, path): open(path, "w").write("png")
        async def title(self): return "测试页"
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())

    def fail_complete(*a, **k):
        raise AssertionError("error 归因本轮不触发（截图缺失，勿调 LLM）")
    monkeypatch.setattr(rm, "complete", fail_complete)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "execute" and body["status"] == "error"
    assert body["executed"] is None and body["assertion_results"] is None
    assert "net reset" in (body.get("attribution") or "")
