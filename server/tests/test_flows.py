"""S19 T1/T2：流程生成（synth_flow）提案/回查 + 执行 API 测试。

FakeProvider 铁律：LLM_API_KEY 置空 + LLM_FAKE_RESPONSE 脚本化响应。
证据收集：直插 skill（含骨架签名/输入变量）+ alignment 首会话 navigation
raw_event（pages URL 来源）。
"""
import json
import uuid

import pytest


def _seed_skill(signatures, variables=(), nav_urls=(), status="learned"):
    """直插 1 个 skill：骨架签名列表 + 输入变量名 + alignment 首会话
    navigation 事件 URL（collect_evidence 的 pages 数据源）。返回 skill id。"""
    from app.db import SessionLocal
    from app.models import Alignment, RawEvent, Skill
    db = SessionLocal()
    try:
        sid = f"s-{uuid.uuid4().hex[:8]}"
        alignment = Alignment(session_ids=[sid], skeleton=[], param_variables=[],
                              input_variables=[])
        db.add(alignment)
        db.flush()
        for i, url in enumerate(nav_urls):
            db.add(RawEvent(session_id=sid, page_id="", seq=i, ts=i,
                            kind="navigation", payload={"url": url}))
        skill = Skill(
            alignment_id=alignment.id,
            name="SeededFlow", description="d", status=status,
            skeleton=[{"signature": s} for s in signatures],
            param_variables=[],
            input_variables=[{"name": v} for v in variables],
            confidence=0.5, evidence_count=1)
        db.add(skill)
        db.commit()
        return skill.id
    finally:
        db.close()


_API_SKILL = ("click:搜索|GET:/api/web/search",)
_GOOD_STEPS = [
    {"kind": "goto", "target": "http://t/search"},
    {"kind": "input", "target": "关键词", "value": "低代码"},
    {"kind": "click", "target": "搜索"},
]


async def _generate(client, monkeypatch, goal="搜索低代码并点击结果",
                    system_hint="/api", steps=None, raw=None):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    if raw is None:
        raw = json.dumps({"steps": steps if steps is not None else _GOOD_STEPS})
    monkeypatch.setenv("LLM_FAKE_RESPONSE", raw)
    return await client.post("/api/v1/flows/generate",
                             json={"goal": goal, "system_hint": system_hint})


# ---------------------------------------------------------------------------
# Task 1：提案生成 + 确定性回查
# ---------------------------------------------------------------------------

async def test_generate_flow_lands_proposed(client, monkeypatch):
    """T1：生成落库字段齐——steps/status=proposed/notes 空/evidence_refs；
    LLM 调用落 llm_call_log purpose=flow_synthesis（C3）；列表倒序 + 详情。"""
    skill_id = _seed_skill(_API_SKILL, variables=("关键词",),
                           nav_urls=("http://t/search",))
    r = await _generate(client, monkeypatch)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "proposed"
    assert body["notes"] == ""
    assert body["steps"] == _GOOD_STEPS

    from app.db import SessionLocal
    from app.models import LlmCallLog, SynthFlow
    db = SessionLocal()
    try:
        n = db.query(LlmCallLog).filter(
            LlmCallLog.purpose == "flow_synthesis").count()
        assert n == 1                                 # C3：目标分解调用落库
        row = db.get(SynthFlow, body["id"])
        assert row.goal.startswith("搜索低代码")
        assert row.system_hint == "/api"
        assert row.execution_log is None              # 执行 T2 才写
        assert row.created_at is not None
        refs = row.evidence_refs
        assert refs["skill_ids"] == [skill_id]
        assert refs["anchors"] == ["搜索"]
        assert refs["variables"] == ["关键词"]
        assert refs["pages"] == ["http://t/search"]
        assert refs["api_templates"] == ["/api/web/search"]
    finally:
        db.close()

    rows = (await client.get("/api/v1/flows")).json()
    assert [x["id"] for x in rows] == [body["id"]]
    detail = (await client.get(f"/api/v1/flows/{body['id']}")).json()
    assert detail["status"] == "proposed"
    assert detail["steps"] == _GOOD_STEPS


async def test_generate_flow_unknown_anchor_stays_proposed_notes(client, monkeypatch):
    """T1：LLM 给未知锚点 → 回查失败，仍落库 proposed + notes 记原因。"""
    _seed_skill(_API_SKILL, variables=("关键词",), nav_urls=("http://t/search",))
    bad = [*_GOOD_STEPS[:2], {"kind": "click", "target": "不存在的按钮"}]
    r = await _generate(client, monkeypatch, steps=bad)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "proposed"
    assert "回查失败" in body["notes"] or "锚点" in body["notes"]
    assert body["steps"] == bad                     # 仍落库供人工看


async def test_generate_flow_unparseable_response_notes(client, monkeypatch):
    """T1：LLM 响应非 JSON → proposed + notes 记无法解析（复用解析模式）。"""
    _seed_skill(_API_SKILL, variables=("关键词",), nav_urls=("http://t/search",))
    r = await _generate(client, monkeypatch, raw="垃圾输出非 JSON")
    body = r.json()
    assert body["status"] == "proposed"
    assert "无法解析" in body["notes"]


async def test_generate_flow_empty_steps_notes(client, monkeypatch):
    """T1：steps 空列表 → 回查失败 proposed + notes。"""
    _seed_skill(_API_SKILL, variables=("关键词",), nav_urls=("http://t/search",))
    r = await _generate(client, monkeypatch, steps=[])
    body = r.json()
    assert body["status"] == "proposed"
    assert "steps" in body["notes"]


async def test_get_flow_404(client):
    resp = await client.get("/api/v1/flows/99999")
    assert resp.status_code == 404


async def test_collect_evidence_filters_by_system_hint(client):
    """T1：system_hint 过滤——/codeBack skill 不进 /api 证据集
    （anchors/variables/pages 跟随匹配的 skill）。"""
    from app.db import SessionLocal
    from app.learning.synthesis import collect_evidence
    _seed_skill(("click:保存|POST:/codeBack/formConfig/save",),
                variables=("表单名",), nav_urls=("http://t/codeBack",))
    _seed_skill(_API_SKILL, variables=("关键词",), nav_urls=("http://t/search",))
    db = SessionLocal()
    try:
        ev = collect_evidence(db, "/api")
        assert ev["api_templates"] == {"/api/web/search"}
        assert ev["anchors"] == {"搜索"}             # /codeBack 的"保存"不进集
        assert ev["variables"] == {"关键词"}
        assert ev["pages"] == {"http://t/search"}
    finally:
        db.close()


def test_verify_steps_each_kind():
    """T1 纯函数：各 kind 校验——kind 白名单/goto 页面子串/input 变量精确/
    click 锚点子串；失败记 why。"""
    from app.learning.synthesis import verify_steps
    ev = {"anchors": {"搜索"}, "variables": {"关键词"},
          "pages": {"http://t/search?x=1"}, "api_templates": set()}
    ok, why = verify_steps(_GOOD_STEPS, ev)
    assert ok and why == ""
    # goto 目标不在已知页面
    ok, why = verify_steps([{"kind": "goto", "target": "http://unknown/"}], ev)
    assert not ok and "页面" in why
    # input 目标不在已知变量
    ok, why = verify_steps([{"kind": "input", "target": "未知变量", "value": "v"}], ev)
    assert not ok and "变量" in why
    # click 锚点未知
    ok, why = verify_steps([{"kind": "click", "target": "不存在"}], ev)
    assert not ok and "锚点" in why
    # kind 白名单
    ok, why = verify_steps([{"kind": "delete", "target": "x"}], ev)
    assert not ok and "kind" in why
    # 空列表
    ok, why = verify_steps([], ev)
    assert not ok and "steps" in why


# ---------------------------------------------------------------------------
# Task 2：执行 + C1 门控 + 自学习提示
# ---------------------------------------------------------------------------

def _insert_flow(steps, status="proposed"):
    from app.db import SessionLocal
    from app.models import SynthFlow
    db = SessionLocal()
    try:
        row = SynthFlow(goal="测试流程", system_hint="/api", steps=steps,
                        status=status, evidence_refs={})
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


async def test_execute_write_anchor_gated_409(client):
    """T2：click 锚点关联写 API（POST）+ 未 confirm → 409（C1 零例外）。"""
    _seed_skill(("click:保存|POST:/api/form/save",))
    flow_id = _insert_flow([{"kind": "click", "target": "保存"}])
    resp = await client.post(f"/api/v1/flows/{flow_id}/execute",
                             json={"confirm_side_effect": False})
    assert resp.status_code == 409
    assert "写操作" in resp.json()["detail"]


async def test_execute_readonly_anchor_not_gated(client, monkeypatch):
    """T2：GET-only 锚点不触发 C1 门控（查询无副作用不算）——
    200 直达执行（替身浏览器，locate 失败 → failed 收敛，C3 日志落库）。"""
    import app.replay.flow_runner as fr
    monkeypatch.setattr(fr, "_launch", lambda: _FakePW(_FakePage()))

    async def locate(page, label):
        raise LookupError(f"semantic locate failed: {label!r}")

    monkeypatch.setattr(fr, "locate", locate)
    _seed_skill(_API_SKILL)                          # click:搜索|GET:/api/...
    flow_id = _insert_flow([{"kind": "click", "target": "搜索"}])
    resp = await client.post(f"/api/v1/flows/{flow_id}/execute",
                             json={"confirm_side_effect": False})
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"         # 无匹配锚点→执行失败收敛
    assert isinstance(resp.json()["execution_log"], list)


async def test_execute_success_lands_executed(client, monkeypatch):
    """T2：FakePage 替身执行 goto+input+click → executed + execution_log
    全 ok + notes 记自学习提示（v1 不自动 induce）。"""
    import app.replay.flow_runner as fr
    page = _FakePage()
    monkeypatch.setattr(fr, "_launch", lambda: _FakePW(page))
    monkeypatch.setattr(fr, "locate", _fake_locate)
    flow_id = _insert_flow(list(_GOOD_STEPS))
    resp = await client.post(f"/api/v1/flows/{flow_id}/execute",
                             json={"confirm_side_effect": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "executed"
    assert page.gotos == ["http://t/search"]
    log = body["execution_log"]
    assert [e["step"] for e in log] == [1, 2, 3]
    assert all(e["ok"] for e in log)
    assert "执行成功" in body["notes"]
    assert "插件录制" in body["notes"]

    from app.db import SessionLocal
    from app.models import SynthFlow
    db = SessionLocal()
    try:
        row = db.get(SynthFlow, flow_id)
        assert row.status == "executed"              # 落库持久化
        assert row.execution_log and all(e["ok"] for e in row.execution_log)
    finally:
        db.close()


async def test_execute_failure_converges(client, monkeypatch):
    """T2：中间步异常 → status=failed + execution_log 记错误步，
    后续步 not attempted（失败收敛）。"""
    import app.replay.flow_runner as fr
    page = _FakePage()
    monkeypatch.setattr(fr, "_launch", lambda: _FakePW(page))

    async def locate(page, label):
        if label == "搜索":
            raise LookupError(f"semantic locate failed: {label!r}")
        return _FakeLocator(), "fake"

    monkeypatch.setattr(fr, "locate", locate)
    flow_id = _insert_flow(list(_GOOD_STEPS))
    resp = await client.post(f"/api/v1/flows/{flow_id}/execute",
                             json={"confirm_side_effect": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    log = body["execution_log"]
    assert [e["ok"] for e in log] == [True, True, False]
    assert "搜索" in log[2]["error"]
    assert "not attempted" not in [e.get("error") for e in log[:3]]


async def test_execute_missing_404(client):
    resp = await client.post("/api/v1/flows/99999/execute",
                             json={"confirm_side_effect": False})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 浏览器替身：FakePage/FakeLocator（monkeypatch locate，不碰真实浏览器）
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self):
        self.filled = []
        self.clicked = 0

    async def fill(self, value, timeout=None):
        self.filled.append(value)

    async def click(self, timeout=None):
        self.clicked += 1


async def _fake_locate(page, label):
    return _FakeLocator(), "fake"


class _FakePage:
    def __init__(self):
        self.gotos = []

    async def goto(self, url):
        self.gotos.append(url)

    async def wait_for_timeout(self, ms):
        pass


class _FakePW:
    """runner._open_browser 按能力分发：无 chromium 属性 → chromium_launch。"""

    def __init__(self, page):
        self._page = page

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def chromium_launch(self):
        return _FakeBrowser(self._page)


class _FakeBrowser:
    def __init__(self, page):
        self._page = page

    async def new_context(self, storage_state=None):
        return _FakeCtx(self._page)

    async def close(self):
        pass


class _FakeCtx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page
