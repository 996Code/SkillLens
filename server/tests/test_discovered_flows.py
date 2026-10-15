"""AP3 discovery flow + human review contract tests."""
import json

import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import RawEvent, RecordingSession


async def _seed_ambient_session(client: AsyncClient, events: list[dict]) -> str:
    r = await client.post("/api/v1/sessions", json={
        "target_system": "ruoyi", "note": "(ambient 自动录制)",
        "source": "ambient",
    }, headers={"X-SkillLens-Agent": "1"})
    sid = r.json()["session_id"]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events,
                      headers={"X-SkillLens-Agent": "1"})
    return sid


def _task_events() -> list[dict]:
    """一段过闸的任务流：导航+输入+提交+写请求（≥5 事件，有写）。"""
    return [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/system/post"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "新增"}}},
        {"seq": 2, "ts": 2000, "kind": "action",
         "payload": {"type": "input", "name": "名称", "value": "测试岗"}},
        {"seq": 3, "ts": 3000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 4, "ts": 3500, "kind": "network",
         "payload": {"method": "POST", "url": "/system/post", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]


async def test_segment_creates_pending_flow(client: AsyncClient):
    """ambient 会话切分：过闸段 → 待发现；discard 段留痕（C3）。"""
    sid = await _seed_ambient_session(client, _task_events())
    r = await client.post(f"/api/v1/sessions/{sid}/segment")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["flows"] >= 1, "过闸任务流应进待发现"
    assert body["discarded"] >= 0

    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    assert any(f["session_id"] == sid for f in lst)
    item = next(f for f in lst if f["session_id"] == sid)
    assert item["event_count"] >= 5
    assert item["has_write"] is True


async def test_confirm_flow_creates_candidate_skill(client: AsyncClient,
                                                     monkeypatch):
    """确认待发现流 → 复制段事件成新会话 → 既有 align/induce 管道 →
    candidate 技能（LLM 命名走 fake）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "PostCreate",
                                   "description": "用户创建岗位"}))
    sid = await _seed_ambient_session(client, _task_events())
    seg = (await client.post(f"/api/v1/sessions/{sid}/segment")).json()
    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    flow = next(f for f in lst if f["session_id"] == sid)

    r = await client.post(f"/api/v1/discovered-flows/{flow['id']}/confirm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["skill_id"], "确认后应产出技能"
    assert body["skill_name"] == "PostCreate"

    # 技能走既有晋升轨道（verify 过=learned；不过=candidate）
    from app.models import Skill
    db = SessionLocal()
    try:
        sk = db.get(Skill, body["skill_id"])
        assert sk.status in ("candidate", "learned")
        assert sk.description == "用户创建岗位"
    finally:
        db.close()


async def test_discard_flow_leaves_audit_trail(client: AsyncClient):
    """丢弃待发现流：状态落库可审计（C3），不静默消失。"""
    sid = await _seed_ambient_session(client, _task_events())
    await client.post(f"/api/v1/sessions/{sid}/segment")
    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    flow = next(f for f in lst if f["session_id"] == sid)

    r = await client.post(f"/api/v1/discovered-flows/{flow['id']}/discard")
    assert r.status_code == 200
    assert r.json()["status"] == "discarded"
    # pending 队列不再含
    lst2 = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    assert all(f["id"] != flow["id"] for f in lst2)
    # 但审计视图可查
    allf = (await client.get("/api/v1/discovered-flows")).json()
    assert any(f["id"] == flow["id"] and f["status"] == "discarded" for f in allf)


async def test_noise_session_segments_to_discard_only(client: AsyncClient):
    """纯浏览 ambient 会话：全部段被闸——不进待发现（防学习管道被冲垮）。"""
    noise = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/list"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "菜单"}}},
        {"seq": 2, "ts": 2000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "菜单2"}}},
        {"seq": 3, "ts": 3000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "菜单3"}}},
        {"seq": 4, "ts": 4000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "菜单4"}}},
    ]
    sid = await _seed_ambient_session(client, noise)
    r = await client.post(f"/api/v1/sessions/{sid}/segment")
    assert r.json()["flows"] == 0, "纯浏览零待发现"
    assert r.json()["discarded"] >= 1
