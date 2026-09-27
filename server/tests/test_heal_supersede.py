"""S26：自愈晋升回写 skill 骨架（TDD 先红，多维度）。

- 骨架步 label 覆盖：compile_skeleton_plan 优先取 step["label"]（单元）；
- 自动晋升（N=1）→ 生成新版本 skill（v2，骨架含 healed label，断言已复制，
  旧版本 superseded）→ 新版本回放**无需提案**直接 pass；
- 人工 promote 端点：reviewer 200 → 版本生成；viewer 403；
- 旧版本回放 409 superseded。
"""
import json

from playwright.async_api import async_playwright

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


def test_skeleton_label_override_precedence():
    """骨架步显式 label 优先于录制事件里的 anchor label（回写生效的核心）。"""
    from app.replay.plan import compile_skeleton_plan
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://mock.local/"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
    ]
    skeleton = [{"signature": "click:保存",
                 "session_window_seqs": {"s1": 0},
                 "label": "提交表单"}]     # S26：healed label
    plan = compile_skeleton_plan(events, skeleton, "s1", {}, [])
    clicks = [s for s in plan["steps"] if s["kind"] == "click"]
    assert clicks and clicks[0]["label"] == "提交表单"


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


async def _replay(skill_id, monkeypatch, html):
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
            run = await rm.run_replay(db, skill_id, {"请输入": "注入值"}, True)
            db.refresh(run)
            return run
        finally:
            db.close()


async def test_auto_promote_creates_new_skill_version(client, monkeypatch):
    """改名→提案→自愈一次（N=1）→ 自动晋升生成 v2：骨架 healed、断言复制、
    旧版 superseded；v2 回放无需提案直接 pass。"""
    from app.db import SessionLocal
    from app.models import LocateProposal, OutcomeAssertion, Skill
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LOCATE_AUTO_PROMOTE_N", "1")
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")

    run1 = await _replay(skill["id"], monkeypatch, FORM_HTML_V2)
    assert run1.status == "fail"
    run2 = await _replay(skill["id"], monkeypatch, FORM_HTML_V2)
    assert run2.status == "pass"          # 经提案自愈

    db = SessionLocal()
    try:
        old = db.get(Skill, skill["id"])
        assert old.status == "superseded" and old.superseded_by is not None
        new = db.get(Skill, old.superseded_by)
        assert new.version == (old.version or 1) + 1
        # 骨架 healed：匹配 step_label 的骨架步带 label 覆盖
        healed = [s for s in new.skeleton
                  if s.get("label") == "提交表单"
                  and "保存" in s.get("signature", "")]
        assert healed, new.skeleton
        # 断言已复制到新版本
        n_new = db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == new.id).count()
        n_old = db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == old.id).count()
        assert n_new == n_old and n_new > 0
        # 提案记录 applied_skill_id
        prop = db.query(LocateProposal).filter_by(step_label="保存").first()
        assert prop.applied_skill_id == new.id
        new_id = new.id
    finally:
        db.close()

    # 新版本回放：无需提案（骨架 label 已 healed）直接 pass
    run3 = await _replay(new_id, monkeypatch, FORM_HTML_V2)
    assert run3.status == "pass"
    click3 = [s for s in run3.executed if s.get("kind") == "click"][0]
    assert "repair_proposal_id" not in click3      # 不是靠提案兜底
    assert click3["label"] == "提交表单"

    # 旧版本回放 → 409 superseded
    resp = await client.post(f"/api/v1/skills/{skill['id']}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    assert resp.status_code == 409


async def test_manual_promote_endpoint_roles(client, monkeypatch):
    """人工 promote：reviewer 提前晋升生成版本；viewer 403。"""
    from app.auth import create_user, issue_token
    from app.db import SessionLocal
    from app.models import LocateProposal, Skill
    skill = await _prepare_skill(client, monkeypatch)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交表单")
    await _replay(skill["id"], monkeypatch, FORM_HTML_V2)   # 生成 verified 提案

    db = SessionLocal()
    try:
        prop = db.query(LocateProposal).filter_by(step_label="保存").first()
        pid = prop.id
        reviewer = create_user(db, "s26-rev", "pw", "reviewer")
        rtoken = issue_token(db, reviewer.id)
        viewer = create_user(db, "s26-view", "pw", "viewer")
        vtoken = issue_token(db, viewer.id)
    finally:
        db.close()

    resp = await client.post(f"/api/v1/locate-proposals/{pid}/promote",
                             headers={"Authorization": f"Bearer {vtoken}"})
    assert resp.status_code == 403

    resp = await client.post(f"/api/v1/locate-proposals/{pid}/promote",
                             headers={"Authorization": f"Bearer {rtoken}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "promoted" and body["applied_skill_id"]

    db = SessionLocal()
    try:
        old = db.get(Skill, skill["id"])
        assert old.status == "superseded"
    finally:
        db.close()
