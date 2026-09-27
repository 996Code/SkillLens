"""S25 块 W T2：Webhook 通知（TDD 先红）。

- 四格式 payload（wecom/dingtalk/slack/generic）结构正确；
- WEBHOOK_URL 空 → 零调用（默认关闭）；
- 报告生成触发一次推送（fire-and-forget，失败不阻塞主流程）。
"""
import json

import httpx
import pytest

from app.integrations.webhook import build_payload, notify


def test_payload_wecom():
    p = build_payload("wecom", "标题", "内容摘要")
    assert p == {"msgtype": "markdown", "markdown": {"content": "## 标题\n内容摘要"}}


def test_payload_dingtalk():
    p = build_payload("dingtalk", "标题", "内容摘要")
    assert p == {"msgtype": "markdown", "markdown": {"title": "标题", "text": "#### 标题\n内容摘要"}}


def test_payload_slack():
    p = build_payload("slack", "标题", "内容摘要")
    assert p == {"text": "*标题*\n内容摘要"}


def test_payload_generic():
    p = build_payload("generic", "标题", "内容摘要")
    assert p == {"title": "标题", "body": "内容摘要"}


def test_payload_unknown_format_falls_back_generic():
    assert build_payload("nope", "t", "b") == {"title": "t", "body": "b"}


async def test_notify_posts_to_url(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), json.loads(request.read())))
        return httpx.Response(200)

    monkeypatch.setenv("WEBHOOK_URL", "https://hook.example/x")
    monkeypatch.setenv("WEBHOOK_FORMAT", "slack")
    import importlib
    import app.config
    importlib.reload(app.config)  # notify 调用时读 env，此处只为一致性
    ok = await notify("报告生成", "report #9 四分类完成", transport=httpx.MockTransport(transport_handler))
    assert ok is True
    assert len(calls) == 1
    assert calls[0][1] == {"text": "*报告生成*\nreport #9 四分类完成"}


async def test_notify_disabled_when_url_empty(monkeypatch):
    calls: list = []

    def transport_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    monkeypatch.setenv("WEBHOOK_URL", "")
    ok = await notify("标题", "内容", transport=httpx.MockTransport(transport_handler))
    assert ok is False
    assert calls == []


async def test_notify_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("WEBHOOK_URL", "https://hook.example/x")

    def transport_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    ok = await notify("标题", "内容", transport=httpx.MockTransport(transport_handler))
    assert ok is False  # fire-and-forget：失败返回 False 不抛


async def test_report_generation_triggers_webhook(client, monkeypatch):
    """触发点：报告生成 → 一次推送（含报告 id 与四分类计数）。"""
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
    delta = (await client.post("/api/v1/expected-deltas", json={
        "requirement_id": "w2-req", "requirement_text": "测试"})).json()
    delta = (await client.post(f"/api/v1/expected-deltas/{delta['id']}/confirm",
                              json={"reviewed_by": "w2",
                                    "changes": [{"type": "api_add", "value": "/a/1/save"}]})).json()

    from app.db import SessionLocal
    from app.models import ObservedDelta
    db = SessionLocal()
    try:
        db.add(ObservedDelta(expected_delta_id=delta["id"], skill_id=skill["id"],
                             replay_run_id=1, items=[], duration_ms=0))
        db.commit()
        obs_id = db.query(ObservedDelta).order_by(ObservedDelta.id.desc()).first().id
    finally:
        db.close()

    sent: list[dict] = []

    async def fake_notify(title, body, **kw):
        sent.append({"title": title, "body": body})
        return True
    monkeypatch.setenv("WEBHOOK_URL", "https://hook.example/x")
    # report 端点函数内局部导入 → patch 源模块属性
    import app.integrations.webhook as webhook_mod
    monkeypatch.setattr(webhook_mod, "notify", fake_notify)

    resp = await client.post(f"/api/v1/expected-deltas/{delta['id']}/report",
                             json={"observed_delta_id": obs_id})
    assert resp.status_code == 201
    assert len(sent) == 1
    assert "报告" in sent[0]["title"]
    assert str(resp.json()["id"]) in sent[0]["body"]
