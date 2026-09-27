"""S24 块 U T2/T3：定位修复提案——自愈闭环（TDD 先红，多维度）。

维度覆盖：
- 集成：按钮改名→定位失败→LLM 提案+确定性验证→再回放自愈通过→N 次后自动晋升；
- 负例：LLM 提案不存在的标签→停留 proposed，回放不使用；
- 人工否决：rejected 提案不参与回放；
- 角色：reject viewer 403 / reviewer 200；
- API：提案列表含源 run 归因（U3 链路）。
"""
import json

from playwright.async_api import async_playwright

# 录制时按钮叫"保存"；回放页面按钮改名为"保存修改"（定位失败场景）
FORM_HTML_V1 = """<html><body>
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

FORM_HTML_V2 = FORM_HTML_V1.replace(">保存<", ">提交表单<")


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


async def _replay(skill, monkeypatch, html):
    import app.replay.runner as rm
    from app.db import SessionLocal
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()

        async def handle_save(route):
            await route.fulfill(status=200, body='{"code":200}')
        await page.route("**/a/1/save", handle_save)
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))
        db = SessionLocal()
        try:
            run = await rm.run_replay(db, skill["id"], {"请输入": "注入值"}, True)
            db.refresh(run)
            return run
        finally:
            db.close()


async def test_locate_repair_full_cycle(client, monkeypatch):
    """改名→失败→提案验证→自愈通过→自动晋升（N=1）。"""
    from app.db import SessionLocal
    from app.models import LocateProposal
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LOCATE_AUTO_PROMOTE_N", "1")

    # 第一次回放：按钮已改名 → 定位失败 → LLM 提案"保存修改" → 确定性验证通过
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")
    run1 = await _replay(skill, monkeypatch, FORM_HTML_V2)
    assert run1.status == "fail"
    db = SessionLocal()
    try:
        row = db.query(LocateProposal).filter_by(
            skill_id=skill["id"], step_label="保存").first()
    finally:
        db.close()
    assert row is not None
    assert row.proposed_label == "提交表单"
    assert row.status == "verified"          # locate 实测命中才 verified
    assert row.source_run_id == run1.id      # U3：提案关联源 run

    # 第二次回放：verified 提案参与自愈 → click 经 repair 成功 → pass
    run2 = await _replay(skill, monkeypatch, FORM_HTML_V2)
    assert run2.status == "pass"
    click_step = [s for s in run2.executed if s.get("kind") == "click"][0]
    assert click_step["ok"] is True
    assert click_step.get("repair_proposal_id") == row.id
    assert click_step["strategy"].startswith("repair:")

    # 使用一次后（N=1）自动晋升
    db = SessionLocal()
    try:
        row = db.query(LocateProposal).get(row.id)
        assert row.status == "promoted"
        assert row.verify_count == 1
    finally:
        db.close()


async def test_unverified_proposal_not_used(client, monkeypatch):
    """负例：LLM 提案不存在的标签 → 停留 proposed，回放不使用（仍失败）。"""
    from app.db import SessionLocal
    from app.models import LocateProposal
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "不存在的按钮")
    run1 = await _replay(skill, monkeypatch, FORM_HTML_V2)
    assert run1.status == "fail"
    db = SessionLocal()
    try:
        row = db.query(LocateProposal).filter_by(
            skill_id=skill["id"], step_label="保存").first()
        assert row is not None
        assert row.status == "proposed"       # locate 实测未命中 → 不验证
    finally:
        db.close()

    # 再回放：proposed 不参与 → 仍失败
    run2 = await _replay(skill, monkeypatch, FORM_HTML_V2)
    assert run2.status == "fail"


async def test_rejected_proposal_not_used(client, monkeypatch):
    """人工否决：rejected 提案不参与回放自愈。"""
    from app.db import SessionLocal
    from app.models import LocateProposal
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")
    await _replay(skill, monkeypatch, FORM_HTML_V2)
    db = SessionLocal()
    try:
        row = db.query(LocateProposal).filter_by(
            skill_id=skill["id"], step_label="保存").first()
        pid = row.id
    finally:
        db.close()

    resp = await client.post(f"/api/v1/locate-proposals/{pid}/reject")
    assert resp.status_code == 200

    run2 = await _replay(skill, monkeypatch, FORM_HTML_V2)
    assert run2.status == "fail"              # rejected 不参与 → 仍失败


async def test_reject_role_control(client, monkeypatch):
    """角色维度：viewer 否决 403。"""
    from app.auth import create_user, issue_token
    from app.db import SessionLocal
    from app.models import LocateProposal
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")
    await _replay(skill, monkeypatch, FORM_HTML_V2)
    db = SessionLocal()
    try:
        row = db.query(LocateProposal).filter_by(
            skill_id=skill["id"]).first()
        pid = row.id
        viewer = create_user(db, "s24-viewer", "pw", "viewer")
        vtoken = issue_token(db, viewer.id)
    finally:
        db.close()
    resp = await client.post(f"/api/v1/locate-proposals/{pid}/reject",
                             headers={"Authorization": f"Bearer {vtoken}"})
    assert resp.status_code == 403


async def test_proposal_list_with_attribution(client, monkeypatch):
    """U3：提案列表含源 run 归因摘要（失败→归因→修复链）。"""
    from app.db import SessionLocal
    from app.models import LocateProposal
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")
    run1 = await _replay(skill, monkeypatch, FORM_HTML_V2)

    resp = await client.get(f"/api/v1/skills/{skill['id']}/locate-proposals")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["step_label"] == "保存"
    assert items[0]["proposed_label"] == "提交表单"
    assert items[0]["source_run_id"] == run1.id
    assert items[0]["attribution"] is not None   # 归因文本（fake 响应）
