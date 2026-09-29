"""S22 块 T T2/T3：视觉基线生命周期 + runner 集成 + API（TDD 先红）。

场景（真实 Playwright page + route mock，同 test_runner_browser 模式）：
1. execute PASS → 建基线（表行 + baseline.png）；
2. 页面改版（加大面积色块，表单行为不变）→ 再回放 → visual_baseline 断言 fail → run fail；
3. 重置基线（reviewer 200 / viewer 403）→ 行删除，下次 PASS 重建。
"""
import json

import pytest
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

# 改版页：表单行为一致 + 40% 高度的大红块（视觉差异远超 2% 阈值）
FORM_HTML_V2 = """<html><body>
<div style="height:40vh;background:#ff0000">NEW BANNER</div>
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
    """录制→对齐→归纳→断言，返回 skill。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://mock.local/"}},
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
    aid = (await client.post("/api/v1/align",
                            json={"session_ids": [sid, sid]})).json()["alignment_id"]
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


async def _replay(skill, html, monkeypatch, overrides=None):
    """route mock 页面 + 走 runner.run_replay（execute）。"""
    import app.replay.runner as rm
    from app.db import SessionLocal
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))

        async def handle_save(route):
            await route.fulfill(status=200, body='{"code":200}')
        await page.route("**/a/1/save", handle_save)
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))
        db = SessionLocal()
        try:
            run = await rm.run_replay(db, skill["id"],
                                      overrides if overrides is not None else {"请输入": "注入值"},
                                      True)
            db.refresh(run)  # 预载属性，避免 close 后 DetachedInstanceError
            return run
        finally:
            db.close()


async def test_pass_creates_visual_baseline(client, monkeypatch):
    from app.db import SessionLocal
    from app.models import VisualBaseline
    skill = await _prepare_skill(client, monkeypatch)
    run = await _replay(skill, FORM_HTML, monkeypatch)
    assert run.status == "pass"
    db = SessionLocal()
    try:
        row = db.query(VisualBaseline).filter_by(skill_id=skill["id"]).first()
    finally:
        db.close()
    assert row is not None
    assert row.source_run_id == run.id
    import os
    assert os.path.exists(row.file_path)


async def test_visual_regression_flips_run_to_fail(client, monkeypatch):
    from app.models import VisualBaseline
    skill = await _prepare_skill(client, monkeypatch)
    run1 = await _replay(skill, FORM_HTML, monkeypatch)
    assert run1.status == "pass"

    # 页面改版：表单行为不变（其余断言过），视觉大改 → visual 断言 fail
    run2 = await _replay(skill, FORM_HTML_V2, monkeypatch, overrides={})
    assert run2.status == "fail"
    visual = [r for r in run2.assertion_results
              if (r.get("payload") or {}).get("kind") == "visual_baseline"]
    assert len(visual) == 1
    assert visual[0]["passed"] is False
    assert visual[0]["payload"]["diff_ratio"] > 0.02


async def test_reset_baseline_roles(client, monkeypatch):
    from app.auth import create_user, issue_token
    from app.db import SessionLocal
    from app.models import VisualBaseline
    skill = await _prepare_skill(client, monkeypatch)
    await _replay(skill, FORM_HTML, monkeypatch)

    # viewer 403
    db = SessionLocal()
    try:
        viewer = create_user(db, "s22-viewer", "pw", "viewer")
        vtoken = issue_token(db, viewer.id)
    finally:
        db.close()
    resp = await client.post(f"/api/v1/skills/{skill['id']}/visual-baseline/reset",
                             headers={"Authorization": f"Bearer {vtoken}"})
    assert resp.status_code == 403

    # reviewer 200 → 行删除
    resp = await client.post(f"/api/v1/skills/{skill['id']}/visual-baseline/reset")
    assert resp.status_code == 200
    db = SessionLocal()
    try:
        assert db.query(VisualBaseline).filter_by(skill_id=skill["id"]).first() is None
    finally:
        db.close()

    # 重置后下次 PASS 重建基线
    run3 = await _replay(skill, FORM_HTML, monkeypatch)
    assert run3.status == "pass"
    db = SessionLocal()
    try:
        assert db.query(VisualBaseline).filter_by(skill_id=skill["id"]).first() is not None
    finally:
        db.close()


async def test_visual_baseline_endpoint(client, monkeypatch):
    skill = await _prepare_skill(client, monkeypatch)
    # 无基线 → baseline=null
    resp = await client.get(f"/api/v1/skills/{skill['id']}/visual-baseline")
    assert resp.status_code == 200
    assert resp.json()["baseline"] is None

    await _replay(skill, FORM_HTML, monkeypatch)
    resp = await client.get(f"/api/v1/skills/{skill['id']}/visual-baseline")
    body = resp.json()
    assert body["baseline"]["skill_id"] == skill["id"]

    # 图片端点：基线 200；未知 which 422/404
    resp = await client.get(
        f"/api/v1/skills/{skill['id']}/visual-baseline/image?which=baseline")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


async def test_visual_diff_with_overrides_not_judged(client, monkeypatch):
    """S37 断言语义根治：换参数据回放时页面内容变化是预期（模拟人工用
    不同数据操作），视觉差异记录不判定——消除假阴性。"""
    skill = await _prepare_skill(client, monkeypatch)
    run1 = await _replay(skill, FORM_HTML, monkeypatch, overrides={})
    assert run1.status == "pass"  # 建基线

    # 换参 + 页面变化 → 视觉差异不判定，run 仍 pass
    run2 = await _replay(skill, FORM_HTML_V2, monkeypatch,
                         overrides={"请输入": "另一个值"})
    assert run2.status == "pass"
    visual = [a for a in (run2.assertion_results or [])
              if (a.get("payload") or {}).get("kind") == "visual_baseline"]
    assert visual and visual[0].get("skipped"), visual
