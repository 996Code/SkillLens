"""S23 块 V T1：回放耗时 + API 延迟采集（TDD 先红）。

- 替身回放：run.duration_ms > 0（execute_plan 前后真实时间差）；
- 真实 page（route mock）：plan["api_latencies"] 含命中模板的延迟；
- observed_delta.duration_ms 取 run.duration_ms（兑现 MVP TODO）。
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


async def _replay(skill, monkeypatch):
    import app.replay.runner as rm
    from app.db import SessionLocal
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))

        async def handle_save(route):
            await route.fulfill(status=200, body='{"code":200}')
        await page.route("**/a/1/save", handle_save)
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))
        db = SessionLocal()
        try:
            run = await rm.run_replay(db, skill["id"], {"请输入": "注入值"}, True)
            db.refresh(run)
            return run
        finally:
            db.close()


async def test_duration_ms_recorded(client, monkeypatch):
    skill = await _prepare_skill(client, monkeypatch)
    run = await _replay(skill, monkeypatch)
    assert run.status == "pass"
    assert run.duration_ms is not None and run.duration_ms >= 0


async def test_api_latencies_in_plan(client, monkeypatch):
    skill = await _prepare_skill(client, monkeypatch)
    run = await _replay(skill, monkeypatch)
    lat = (run.plan or {}).get("api_latencies")
    assert isinstance(lat, dict)
    assert "/a/{id}/save" in lat          # 断言模板命中 → 记录延迟
    assert lat["/a/{id}/save"] >= 0


async def test_observed_delta_duration_from_run(client, monkeypatch):
    """MVP TODO 兑现：observed_delta.duration_ms 取回放真实耗时。"""
    from app.change.observed import run_observe
    from app.db import SessionLocal
    from app.models import ExpectedDelta
    skill = await _prepare_skill(client, monkeypatch)

    db = SessionLocal()
    try:
        db.add(ExpectedDelta(requirement_id="perf-req", version=1,
                            requirement_text="测试", changes=[],
                            status="confirmed"))
        db.commit()
        delta = db.query(ExpectedDelta).order_by(ExpectedDelta.id.desc()).first()
        delta_id = delta.id
    finally:
        db.close()

    import app.replay.runner as rm
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))

        async def handle_save(route):
            await route.fulfill(status=200, body='{"code":200}')
        await page.route("**/a/1/save", handle_save)
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))
        db = SessionLocal()
        try:
            row = await run_observe(db, delta_id, skill["id"], {}, True)
        finally:
            db.close()
    assert row.duration_ms is not None and row.duration_ms > 0
