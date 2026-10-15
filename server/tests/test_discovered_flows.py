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


async def test_confirm_creates_scenario_when_requested(client: AsyncClient,
                                                          monkeypatch):
    """AP×AR 衔接：确认+create_scenario=true → 技能+场景（origin=learned）
    一次产出——发现流直接进 AR 主链可执行。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "PostCreate2",
                                   "description": "用户创建岗位"}))
    sid = await _seed_ambient_session(client, _task_events())
    await client.post(f"/api/v1/sessions/{sid}/segment")
    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    flow = next(f for f in lst if f["session_id"] == sid)

    r = await client.post(f"/api/v1/discovered-flows/{flow['id']}/confirm",
                          params={"create_scenario": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill_id"], "技能已产出"
    assert body["scenario_id"], "场景应同步创建"
    assert body["scenario_origin"] == "learned"

    from app.models import Scenario
    db = SessionLocal()
    try:
        sc = db.get(Scenario, body["scenario_id"])
        assert sc.origin == "learned"
        assert sc.steps and sc.steps[0]["skill_id"] == body["skill_id"]
    finally:
        db.close()


async def test_pending_flow_carries_merge_suggestion(client: AsyncClient,
                                                       monkeypatch):
    """归并建议：同系统存在相似骨架技能（Jaccard≥阈值）时，待发现流
    附 similar_skill 提示——只建议不自动执行。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # 先造一个同系统已有技能（骨架与任务流同签名+参考会话派生系统）
    from app.models import Alignment, RawEvent, Skill
    db = SessionLocal()
    try:
        import uuid as _uuid
        ref = f"merge-ref-{_uuid.uuid4().hex[:8]}"
        al = Alignment(session_ids=[ref], skeleton=[], buckets=[],
                       input_variables=[], param_variables=[], window_params={})
        db.add(al)
        db.flush()
        db.add(RawEvent(session_id=ref, seq=0, ts=0, kind="navigation",
                         payload={"type": "page-load",
                                  "url": "http://127.0.0.1:8093/system/post"}))
        existing = Skill(alignment_id=al.id, name="ExistingPostCreate",
                          description="已有技能", status="learned",
                          skeleton=[{"signature": "click:新增"},
                                    {"signature": "input:名称"},
                                    {"signature": "click:确定"},
                                    {"signature": "POST:/system/post"}],
                          param_variables=[], input_variables=[],
                          confidence=0.9, evidence_count=1)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        existing_id = existing.id
    finally:
        db.close()

    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "PostCreate3",
                                   "description": "用户创建岗位"}))
    sid = await _seed_ambient_session(client, _task_events())
    await client.post(f"/api/v1/sessions/{sid}/segment")
    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    flow = next(f for f in lst if f["session_id"] == sid)
    # 待发现流带相似提示（同系统已有相似技能）
    assert flow.get("similar_skill_id") == existing_id, \
        f"应检测到相似技能，got {flow.get('similar_skill_id')}"
    assert flow.get("similar_skill_name") == "ExistingPostCreate"

    # 组链动作化：确认+chain_similar → 相似技能+新技能双步场景
    r = await client.post(f"/api/v1/discovered-flows/{flow['id']}/confirm",
                          params={"chain_similar": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skill_id"]
    assert body["scenario_id"], "组链应建场景"
    assert body["chained_with"] == existing_id

    from app.models import Scenario
    db = SessionLocal()
    try:
        sc = db.get(Scenario, body["scenario_id"])
        assert sc.origin == "learned"
        assert [st["skill_id"] for st in sc.steps] == \
            [existing_id, body["skill_id"]], "双步=相似技能在前+新技能在后"
    finally:
        db.close()


async def test_chain_similar_without_match_creates_no_scenario(
        client: AsyncClient, monkeypatch):
    """无相似技能时 chain_similar 不建场景（不凭空组链）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "LonelyFlow",
                                   "description": "无相似"}))
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/unique/path"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "独有操作A"}}},
        {"seq": 2, "ts": 2000, "kind": "action",
         "payload": {"type": "input", "name": "独有字段", "value": "x"}},
        {"seq": 3, "ts": 3000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "独有提交B"}}},
        {"seq": 4, "ts": 3500, "kind": "network",
         "payload": {"method": "POST", "url": "/unique/submit", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    sid = await _seed_ambient_session(client, events)
    await client.post(f"/api/v1/sessions/{sid}/segment")
    lst = (await client.get("/api/v1/discovered-flows?status=pending")).json()
    flow = next(f for f in lst if f["session_id"] == sid)
    assert not flow.get("similar_skill_id"), "独特签名不应有相似"

    r = await client.post(f"/api/v1/discovered-flows/{flow['id']}/confirm",
                          params={"chain_similar": "true"})
    body = r.json()
    assert body["skill_id"]
    assert "scenario_id" not in body, "无相似时组链不建场景"
    assert not body.get("chained_with")
