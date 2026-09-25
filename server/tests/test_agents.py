"""S13 Task 1（F1）：agent_run 表 + LangGraph 夜间图运行时。

- 三节点夜间图（select_skills → replay_batch → aggregate）在 FakeProvider 真管道上执行，
  节点产物逐段落 agent_run.node_outputs；
- 图内异常（skill 不存在场景）→ status=error + error_text（C3 全链路落库）；
- scheduler：NIGHTLY_CRON 默认 off 不启动；下次 02:00 计算为纯函数。
"""
import json
from datetime import datetime

import app.learning.impact as impact_mod


async def _seed_skill(client, monkeypatch) -> int:
    """FakeProvider 真管道：1 session → process → align → induce → 1 skill + evidence_edge。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
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
    return skill["id"]


def _db():
    from app.db import SessionLocal
    return SessionLocal()


async def test_run_graph_nightly_three_nodes(client, monkeypatch):
    """三节点图执行：agent_run status=finished，node_outputs 三段齐全，
    replay_batch 产物含 run_id（shadow 回放落库）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    from app.agents.runtime import run_graph
    from app.models import AgentRun

    db = _db()
    try:
        run = await run_graph(db, "nightly",
                              {"change_set": {"api_templates": ["POST:/a/{id}/save"]}})
        assert run.status == "finished"
        assert run.finished_at is not None
        assert run.error_text is None
        nodes = [seg["node"] for seg in run.node_outputs]
        assert nodes == ["select_skills", "replay_batch", "aggregate"]

        select = run.node_outputs[0]["output"]
        assert select["skills"] == [skill_id]  # impact 选中该 skill

        rb = run.node_outputs[1]["output"]
        assert rb["replay_results"][0]["skill_id"] == skill_id
        assert rb["replay_results"][0]["run_id"] > 0   # replay_run 已落库
        assert rb["replay_results"][0]["status"] == "shadow"  # C1：夜间批回放默认 shadow

        agg = run.node_outputs[2]["output"]["aggregate"]
        assert agg["total"] == 1 and agg["shadow"] == 1

        # agent_run 持久化可查（C3）
        row = db.get(AgentRun, run.id)
        assert row is not None and row.status == "finished"
        assert row.input == {"change_set": {"api_templates": ["POST:/a/{id}/save"]}}
    finally:
        db.close()


async def test_run_graph_error_captured(client, monkeypatch):
    """图级异常（select_skills 节点抛错）：status=error + error_text。
    单 skill 缺失由 batch 落 error run 不中断图（S13 审查修订：
    夜间回归语义=一个坏 skill 不杀整晚）。"""
    await _seed_skill(client, monkeypatch)

    def fake_analyze(db, api_templates, anchor_labels):
        raise RuntimeError("impact 爆炸-图级")
    monkeypatch.setattr(impact_mod, "analyze_impact", fake_analyze)

    from app.agents.runtime import run_graph

    db = _db()
    try:
        run = await run_graph(db, "nightly",
                              {"change_set": {"api_templates": ["POST:/x"]}})
        assert run.status == "error"
        assert run.error_text  # 异常摘要落库
        assert run.finished_at is not None
        assert run.node_outputs == []  # 首节点即炸，无产物
    finally:
        db.close()


async def test_run_graph_batch_error_run_continues(client, monkeypatch):
    """单 skill 不存在：batch 落 error run，图 finished，aggregate 计 error。"""
    await _seed_skill(client, monkeypatch)

    def fake_analyze(db, api_templates, anchor_labels):
        return {"affected_skills": [{"skill_id": 99999}]}
    monkeypatch.setattr(impact_mod, "analyze_impact", fake_analyze)

    from app.agents.runtime import run_graph

    db = _db()
    try:
        run = await run_graph(db, "nightly",
                              {"change_set": {"api_templates": ["POST:/x"]}})
        assert run.status == "finished"
        segs = {seg["node"]: seg["output"] for seg in run.node_outputs}
        assert segs["replay_batch"]["replay_results"][0]["status"] == "error"
        assert segs["aggregate"]["aggregate"]["error"] == 1
    finally:
        db.close()


async def test_run_graph_unknown_graph_name(client):
    """未注册图名 → status=error（不静默成功）。"""
    from app.agents.runtime import run_graph
    db = _db()
    try:
        run = await run_graph(db, "no_such_graph", {})
        assert run.status == "error"
        assert "no_such_graph" in (run.error_text or "")
    finally:
        db.close()


async def test_scheduler_off_by_default(monkeypatch):
    """NIGHTLY_CRON 缺省 off → 不启动后台循环。"""
    monkeypatch.delenv("NIGHTLY_CRON", raising=False)
    from app.agents.scheduler import start_nightly_scheduler
    assert await start_nightly_scheduler() is None


def test_next_run_at_pure():
    """下次 02:00 计算：已过 02:00 → 次日；未到 → 当日。"""
    from app.agents.scheduler import _next_run_at
    base = datetime(2026, 9, 26, 3, 0, 0)
    assert _next_run_at(base) == datetime(2026, 9, 27, 2, 0, 0)
    early = datetime(2026, 9, 26, 1, 0, 0)
    assert _next_run_at(early) == datetime(2026, 9, 26, 2, 0, 0)
    at_two = datetime(2026, 9, 26, 2, 0, 0)
    assert _next_run_at(at_two) == datetime(2026, 9, 27, 2, 0, 0)
