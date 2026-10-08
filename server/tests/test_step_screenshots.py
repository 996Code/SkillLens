"""S33 链路执行步骤截图：回放每个动作步骤（点击/输入）+ 起始页各拍一张，
plan.step_screenshots 旁挂（零 schema 变更），API 按文件出图。

- execute_plan(shot_dir=...)：每步 executed 条目带 screenshot 文件名（真实
  Playwright 验证文件落盘）
- API 层：FakePage.screenshot 写 PNG 字节 → plan.step_screenshots 出现；
  GET /replay-runs/{id}/step-screenshot 200 image/png；非法/不存在 404
- fail-open：替身无 screenshot 能力 → plan 无 step_screenshots，run 照常判定
"""
import json
from pathlib import Path

from playwright.async_api import async_playwright

from app.replay.runner import ARTIFACT_DIR, execute_plan

FORM_HTML = """
<html><body>
  <input placeholder="请输入" />
  <button role="button">演示</button>
</body></html>
"""

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _seed_skill(client, monkeypatch) -> int:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "StepShot", "description": "d"}))
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


async def test_execute_plan_captures_step_screenshots(tmp_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "请输入", "value": "v1", "original_value": "o"},
            {"kind": "click", "label": "演示"},
        ]}
        shot_dir = tmp_path / "shots"
        result = await execute_plan(page, plan, shot_dir=shot_dir)
        await browser.close()
    assert [s["ok"] for s in result["executed"]] == [True, True]
    # 每步带 screenshot 文件名，且文件真实落盘为 PNG
    names = [s["screenshot"] for s in result["executed"]]
    assert names == ["step-01.png", "step-02.png"]
    for n in names:
        f = shot_dir / n
        assert f.is_file() and f.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


async def test_execute_plan_without_shot_dir_has_no_screenshots():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "click", "label": "演示"},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert "screenshot" not in result["executed"][0]


def _fake_pw_classes(shot_dir: Path):
    """替身浏览器：page.screenshot 写 PNG 字节到 shot_dir（真实文件供 API 读）。"""

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def query_selector_all(self, selector): return []
        async def title(self): return "t"
        async def screenshot(self, path=None):
            Path(path).write_bytes(PNG_BYTES)

    class FakeCtx:
        async def new_page(self): return FakePage()

    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...

    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()

    return FakePW


async def test_replay_run_plan_carries_step_screenshots(client, monkeypatch, tmp_path):
    import app.replay.runner as rm
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        shot_dir = kw.get("shot_dir")
        executed = [
            {"kind": "input", "name": "请输入", "value": "新值", "ok": True,
             "screenshot": "step-01.png"},
            {"kind": "click", "label": "保存", "ok": True,
             "screenshot": "step-02.png"},
        ]
        if shot_dir is not None:
            import os
            os.makedirs(shot_dir, exist_ok=True)
            for name in ("start.png", "step-01.png", "step-02.png"):
                (Path(shot_dir) / name).write_bytes(PNG_BYTES)
        return {"executed": executed,
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"code":200}'}]}

    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: _fake_pw_classes(tmp_path)())
    monkeypatch.setattr(rm, "ARTIFACT_DIR", str(tmp_path))

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {"请输入": "新值"},
                                   "confirm_side_effect": True})
    body = resp.json()
    assert body["status"] == "pass"
    meta = body["plan"]["step_screenshots"]
    assert meta["files"] == ["start.png", "step-01.png", "step-02.png"]
    assert meta["dir"].startswith(str(tmp_path))

    # 出图端点：合法文件 200 PNG；白名单外/不存在 404
    r = await client.get(
        f"/api/v1/replay-runs/{body['id']}/step-screenshot?file=step-01.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    r2 = await client.get(
        f"/api/v1/replay-runs/{body['id']}/step-screenshot?file=../secret.png")
    assert r2.status_code == 404
    r3 = await client.get(
        f"/api/v1/replay-runs/{body['id']}/step-screenshot?file=step-99.png")
    assert r3.status_code == 404


async def test_step_screenshots_failopen_without_capability(client, monkeypatch, tmp_path):
    """替身无 screenshot 方法：plan 无 step_screenshots，run 照常 pass。"""
    import app.replay.runner as rm
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
        async def query_selector_all(self, selector): return []
        # 无 screenshot 方法

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

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    body = resp.json()
    assert body["status"] == "pass"
    assert "step_screenshots" not in body["plan"]


# ---------- 评审#6：快照采集须下探 iframe（禅道综合页面等 iframe 架构） ----------

IFRAME_HTML = """<html><body>
<input placeholder="主字段" value="mv">
<iframe srcdoc='<input placeholder="iframe字段" value="iv">
<input type="password" placeholder="iframe密码" value="sec">
<span class="tag">iframe标签</span>
<span class="message">iframe提示</span>'></iframe>
</body></html>"""


async def test_snapshot_descends_into_iframes():
    """iframe 内表单/标签/toast 必须进快照——只查主 frame 时 ui_text 断言
    静默跳过、toast 通道失效、修复提案池为空。iframe 内密码框同样整体跳过。"""
    from app.replay.page_snapshot import collect_page_snapshot
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(IFRAME_HTML)
        await page.wait_for_timeout(300)   # srcdoc frame 挂载
        snap = await collect_page_snapshot(page)
        await browser.close()
    by_label = {f["label"]: f["value"] for f in snap["forms"]}
    assert "主字段" in by_label and by_label["主字段"] == "mv"
    assert "iframe字段" in by_label and by_label["iframe字段"] == "iv"
    assert "iframe密码" not in by_label          # 密码框跳过是全局红线
    assert any(l["text"] == "iframe标签" for l in snap["labels"])
    assert "iframe提示" in (snap.get("toasts") or [])


async def test_snapshot_caps_global_across_frames():
    """限额是全局总量非逐 frame：3 个 frame 各 30 字段 → 总 50 + overflow。"""
    from app.replay.page_snapshot import collect_page_snapshot
    fields = "".join(f'<input placeholder="f{i}" value="v">' for i in range(30))
    html = ("<html><body>" + fields
            + f"<iframe srcdoc='{fields}'></iframe>"
            + f"<iframe srcdoc='{fields}'></iframe></body></html>")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        await page.wait_for_timeout(300)
        snap = await collect_page_snapshot(page)
        await browser.close()
    assert len(snap["forms"]) == 50
    assert snap["overflow"] is True
