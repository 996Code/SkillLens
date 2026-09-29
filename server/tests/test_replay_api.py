import json

from pathlib import Path

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
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        # T4 快照采集桩：runner 在 execute 前后调 collect_page_snapshot
        async def query_selector_all(self, selector): return []
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
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


class _CountingPW:
    """批回放替身：计数 launch（browser 只开一次）与 new_context（每 skill 一个）。"""

    def __init__(self):
        self.launch_count = 0
        self.browser = _CountingBrowser()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a): ...

    async def chromium_launch(self):
        self.launch_count += 1
        return self.browser


class _CountingBrowser:
    def __init__(self):
        self.new_context_count = 0
        self.pages = []

    async def new_context(self, storage_state=None):
        self.new_context_count += 1
        return _CountingCtx(self)

    async def close(self): ...


class _CountingCtx:
    def __init__(self, browser):
        self._browser = browser

    async def new_page(self):
        page = _BatchFakePage()
        self._browser.pages.append(page)
        return page


class _BatchFakePage:
    async def goto(self, url): ...
    async def wait_for_load_state(self, state, timeout=None): ...
    def on(self, *a): ...
    async def wait_for_timeout(self, ms): ...
    async def screenshot(self, path): open(path, "w").write("png")
    async def title(self): return "测试页"
    # T4 快照采集桩：runner 在 execute 前后调 collect_page_snapshot
    async def query_selector_all(self, selector): return []


async def test_replay_batch_shadow_reuses_browser(client, monkeypatch):
    """S13 F3 + C1：两 skill 批 shadow——两 run mode=shadow 落库；
    shadow 前置门控后全 shadow 批次零 launch（Sprint 4 验收语义：
    shadow 未确认绝不启浏览器），execute_plan 不可达。"""
    skill_a = await _seed_skill(client, monkeypatch)
    skill_b = await _seed_skill(client, monkeypatch, llm_name="SaveForm2")

    pw = _CountingPW()
    monkeypatch.setattr(runner_mod, "_launch", lambda: pw)

    async def fail_if_called(*a, **k):
        raise AssertionError("shadow mode must not execute plan")
    monkeypatch.setattr(runner_mod, "execute_plan", fail_if_called)

    resp = await client.post("/api/v1/skills/replay-batch",
                             json={"skill_ids": [skill_a, skill_b]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert [r["skill_id"] for r in body["results"]] == [skill_a, skill_b]
    assert all(r["mode"] == "shadow" and r["status"] == "shadow"
               for r in body["results"])
    assert all(r["run_id"] > 0 for r in body["results"])   # 两 run 已落库
    assert pw.launch_count == 0                            # C1：全 shadow 批零 launch
    assert pw.browser.new_context_count == 0                # shadow 门控不触 context

    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        runs = db.query(ReplayRun).filter(
            ReplayRun.skill_id.in_([skill_a, skill_b])).all()
        assert len(runs) == 2 and all(r.mode == "shadow" for r in runs)
        assert all(r.plan and r.plan["steps"] for r in runs)  # 计划已编译落库
    finally:
        db.close()


async def test_replay_batch_empty_skill_ids_422(client):
    resp = await client.post("/api/v1/skills/replay-batch",
                             json={"skill_ids": []})
    assert resp.status_code == 422


async def test_replay_batch_execute_serial_artifacts(client, monkeypatch):
    """S13 F3：批 execute（FakePage 替身）——串行执行，两 run 产物齐全，
    browser 开一次、每 skill 各开一个 context（new_context=2）。"""
    skill_a = await _seed_skill(client, monkeypatch)
    skill_b = await _seed_skill(client, monkeypatch, llm_name="SaveForm2")

    pw = _CountingPW()
    monkeypatch.setattr(runner_mod, "_launch", lambda: pw)
    monkeypatch.setattr(runner_mod, "execute_plan", fake_execute_plan_ok)

    resp = await client.post(
        "/api/v1/skills/replay-batch",
        json={"skill_ids": [skill_a, skill_b],
              "overrides_map": {str(skill_a): {"请输入": "批注入值"}},
              "confirm_side_effect": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2 and body["pass_count"] == 2
    assert body["fail_count"] == 0 and body["error_count"] == 0
    assert all(r["mode"] == "execute" and r["status"] == "pass"
               for r in body["results"])

    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        run_a = db.query(ReplayRun).filter(ReplayRun.skill_id == skill_a).one()
        run_b = db.query(ReplayRun).filter(ReplayRun.skill_id == skill_b).one()
        for run in (run_a, run_b):   # 串行产物齐全
            assert run.mode == "execute" and run.status == "pass"
            assert run.executed and run.executed[0]["ok"] is True
            assert run.assertion_results and all(r["passed"]
                                                 for r in run.assertion_results)
            assert run.plan["steps"]
        # overrides_map 按 skill_id 注入（skill_a 有、skill_b 缺省空——无 input 步插入）
        assert run_a.plan["steps"][0]["value"] == "批注入值"
        assert all(s.get("value") != "批注入值" for s in run_b.plan["steps"])
    finally:
        db.close()
    assert pw.launch_count == 1                        # browser 实例复用
    assert pw.browser.new_context_count == 2           # 每 skill 新 context
    assert len(pw.browser.pages) == 2                  # 串行两页


async def test_replay_run_get_404(client):
    resp = await client.get("/api/v1/replay-runs/9999")
    assert resp.status_code == 404


async def test_replay_run_detail_fields(client, monkeypatch):
    """S34：run 详情页数据契约——duration_ms/flaky/created_at 上响应
    （时间线/详情页展示耗时与 flaky 徽标）。"""
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
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    import app.replay.runner as rm
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    run_id = resp.json()["id"]
    detail = (await client.get(f"/api/v1/replay-runs/{run_id}")).json()
    assert detail["duration_ms"] is not None and detail["duration_ms"] >= 0
    assert detail["flaky"] is False
    assert detail["created_at"]


async def fake_execute_plan_ok(page, plan, **kw):
    return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
            "observed": [{"url": "http://t/a/1/save", "status": 200, "body": '{"code":200}'}]}


async def test_storage_state_passed_to_context(client, monkeypatch, tmp_path):
    skill_id = await _seed_skill(client, monkeypatch)

    captured = {}

    class FakeCtx:
        def __init__(self, storage_state=None): captured["state"] = storage_state
        async def new_page(self):
            class P:
                async def goto(self, url): ...
                async def wait_for_load_state(self, state, timeout=None): ...
                def on(self, *a): ...
                async def wait_for_timeout(self, ms): ...
                # T4 快照采集桩
                async def query_selector_all(self, selector): return []
            return P()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx(storage_state)
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()

    import app.replay.runner as rm
    state_file = tmp_path / "state.json"
    state_file.write_text("{}")
    monkeypatch.setattr(rm, "STORAGE_STATE", str(state_file))
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())  # 浏览器入口换成替身
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan_ok)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    assert resp.status_code == 200
    assert captured["state"] == str(state_file)   # 模块常量透传到 new_context


async def test_shadow_never_launches_browser(client, monkeypatch):
    """C1 回归（Sprint 4 验收语义）：shadow 单回放与全 shadow 批次都不启浏览器。"""
    import app.replay.runner as rm
    launches = []

    class NoLaunchPW:
        async def __aenter__(self):
            launches.append("launch")
            raise AssertionError("C1 违规：shadow 路径试图启动浏览器")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(rm, "_launch", lambda: NoLaunchPW())
    skill_id = await _seed_skill(client, monkeypatch)
    # 单回放 shadow
    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": False})
    body = resp.json()
    assert body["mode"] == "shadow" and body["status"] == "shadow"
    assert launches == []
    # 全 shadow 批
    resp2 = await client.post("/api/v1/skills/replay-batch",
                              json={"skill_ids": [skill_id], "confirm_side_effect": False})
    assert resp2.status_code == 200 and resp2.json()["results"][0]["mode"] == "shadow"
    assert launches == []


async def test_run_flow_graph(client, monkeypatch):
    """S38 统一流程图：GET /replay-runs/{id}/flow 返回节点+边+执行注记。
    节点含 page/action/state/assert 四类业务语义；状态节点从
    plan.business_states（执行时派生）读取。"""
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        shot_dir = kw.get("shot_dir")
        import os
        if shot_dir is not None:
            os.makedirs(shot_dir, exist_ok=True)
            for name in ("start.png", "step-01.png"):
                (Path(shot_dir) / name).write_bytes(
                    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00"
                    b"\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89")
        return {"executed": [{"kind": "click", "label": "保存", "ok": True,
                              "strategy": "text", "screenshot": "step-01.png"}],
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"status":"SUCCESS","code":200}'}],
                "observed_toasts": []}

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, state, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def query_selector_all(self, selector): return []
        async def screenshot(self, path=None): pass
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    import app.replay.runner as rm
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())

    r = await client.post(f"/api/v1/skills/{skill_id}/replay",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["id"]
    # plan 落了业务状态
    assert r.json()["plan"]["business_states"] == [
        {"field": "status", "value": "SUCCESS", "source": "GET /a/{id}/save"}]

    flow = (await client.get(f"/api/v1/replay-runs/{run_id}/flow")).json()
    types = [n["type"] for n in flow["nodes"]]
    assert types[0] == "page"
    assert "action" in types
    assert "state" in types  # 业务状态节点
    assert "assert" in types
    # 执行注记：action 节点带截图与成败
    action = next(n for n in flow["nodes"] if n["type"] == "action")
    assert action["status"] == "ok" and action["screenshot"] == "step-01.png"
    # 边连通
    assert len(flow["edges"]) >= len(flow["nodes"]) - 1
