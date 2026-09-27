"""S24 块 U T1：flaky 重跑策略（TDD 先红）——状态化页面多维度验证。

- 首次 500 二次 200：run1 fail → 自动重试 pass → status=pass + flaky=True +
  plan.first_attempt 嵌入失败明细（C3 审计）；
- 关配置（REPLAY_FLAKY_RERUN=0）：保持 fail 不重试；
- 恒定 500：重试仍 fail → 不标 flaky。
"""
import json

from playwright.async_api import async_playwright

FORM_HTML = """<html><body>
<form>
  <input name="请输入" placeholder="请输入"/>
  <button type="submit">保存</button>
</form>
<script>
document.querySelector("button").addEventListener("click", e => {
  e.preventDefault();
  fetch("http://mock.local/a/1/save", {method: "POST", body: "{}"});
});
</script>
</body></html>"""


async def _prepare_skill(client, monkeypatch) -> dict:
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
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill


class _FakePW:
    def __init__(self, page, browser):
        self._page, self._browser = page, browser

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def chromium_launch(self):
        return _FakeBrowser(self._page, self._browser)


class _FakeBrowser:
    def __init__(self, page, browser):
        self._page, self._browser = page, browser

    async def new_context(self, storage_state=None):
        return _FakeCtx(self._page)

    async def close(self):
        pass


class _FakeCtx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


async def _replay(skill, monkeypatch, save_handler):
    """save_handler(route) 决定 /a/1/save 的响应（状态化由闭包计数实现）。"""
    import app.replay.runner as rm
    from app.db import SessionLocal
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        async def handle_save(route):
            await save_handler(route)
        await page.route("**/a/1/save", handle_save)
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))
        db = SessionLocal()
        try:
            run = await rm.run_replay(db, skill["id"], {"请输入": "注入值"}, True)
            db.refresh(run)
            return run
        finally:
            db.close()


async def test_flaky_rerun_passes_second_attempt(client, monkeypatch):
    """状态化页面：首次 500 → fail；自动重试 200 → pass + flaky。"""
    skill = await _prepare_skill(client, monkeypatch)
    calls = {"n": 0}

    async def save_handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            await route.fulfill(status=500, body='{"code":500}')
        else:
            await route.fulfill(status=200, body='{"code":200}')

    run = await _replay(skill, monkeypatch, save_handler)
    assert run.status == "pass"
    assert run.flaky is True
    # C3：首次失败明细嵌入 plan（可审计）
    first = run.plan.get("first_attempt")
    assert first is not None and first["status"] == "fail"
    assert calls["n"] == 2  # 确实重试了一次


async def test_flaky_rerun_disabled(client, monkeypatch):
    """REPLAY_FLAKY_RERUN=0：不重试，保持 fail。"""
    monkeypatch.setenv("REPLAY_FLAKY_RERUN", "0")
    skill = await _prepare_skill(client, monkeypatch)
    calls = {"n": 0}

    async def save_handler(route):
        calls["n"] += 1
        await route.fulfill(status=500, body='{"code":500}')

    run = await _replay(skill, monkeypatch, save_handler)
    assert run.status == "fail"
    assert not run.flaky
    assert calls["n"] == 1


async def test_rerun_still_fails_not_flaky(client, monkeypatch):
    """恒定 500：重试仍 fail → 不标 flaky。"""
    skill = await _prepare_skill(client, monkeypatch)
    calls = {"n": 0}

    async def save_handler(route):
        calls["n"] += 1
        await route.fulfill(status=500, body='{"code":500}')

    run = await _replay(skill, monkeypatch, save_handler)
    assert run.status == "fail"
    assert not run.flaky
    assert calls["n"] == 2


async def test_flaky_visible_in_card_and_consistency(client, monkeypatch):
    """flaky 进一致性统计与卡片概要（多维度：数据出口层）。"""
    skill = await _prepare_skill(client, monkeypatch)
    calls = {"n": 0}

    async def save_handler(route):
        calls["n"] += 1
        if calls["n"] == 1:
            await route.fulfill(status=500, body='{"code":500}')
        else:
            await route.fulfill(status=200, body='{"code":200}')

    run = await _replay(skill, monkeypatch, save_handler)
    assert run.flaky is True

    card = (await client.get(f"/api/v1/skills/{skill['id']}/card")).json()
    assert card["last_run"]["flaky"] is True

    consistency = (await client.get(
        f"/api/v1/skills/{skill['id']}/consistency")).json()
    assert consistency["flaky_runs"] == 1
