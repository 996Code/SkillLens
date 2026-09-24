import json

from tests.test_replay_api import _seed_skill
import app.replay.runner as rm


def _fake_plan_result():
    return {"executed": [
                {"kind": "input", "name": "请输入", "value": "v1", "ok": True},
                {"kind": "click", "label": "保存", "ok": True}],
            "observed": []}


def _mk_fake(execute_result):
    async def fake_execute_plan(page, plan, **kw):
        return execute_result
    return fake_execute_plan


async def _prepare_confirmed_delta(client, monkeypatch, changes):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": changes}))
    body = (await client.post("/api/v1/expected-deltas",
                              json={"requirement_id": "r1",
                                    "requirement_text": "需求"})).json()
    await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                      json={"reviewed_by": "t"})
    return body["id"]


async def test_observe_extracts_and_lands(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    delta_id = await _prepare_confirmed_delta(client, monkeypatch, [
        {"type": "ui_action", "value": "点击 保存"}])

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, s, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()

    result = _fake_plan_result()
    result["observed"] = [
        {"url": "http://t/a/1/save", "status": 200, "body": '{"code":200}'}]
    monkeypatch.setattr(rm, "execute_plan", _mk_fake(result))
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())

    r = await client.post(f"/api/v1/expected-deltas/{delta_id}/observe",
                          json={"skill_id": skill_id, "confirm_side_effect": True})
    assert r.status_code == 201
    body = r.json()
    assert {"type": "ui_action", "value": "点击 保存"} in body["items"]
    assert any(i["type"] == "api_add" and "save" in i["value"] for i in body["items"])
    assert any(i["type"] == "api_status" and "-> 200" in i["value"]
               for i in body["items"])


async def test_observe_rejects_draft(client, monkeypatch):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": [{"type": "ui_action", "value": "A"}]}))
    body = (await client.post("/api/v1/expected-deltas",
                              json={"requirement_id": "r1",
                                    "requirement_text": "需求"})).json()
    r = await client.post(f"/api/v1/expected-deltas/{body['id']}/observe",
                          json={"skill_id": 1, "confirm_side_effect": True})
    assert r.status_code == 409
