"""S43-2 图基座第二步：状态机归纳 + 学习图 + 画布子图展开（TDD 先红）。

- build_state_machine：Skill 多次录制的状态信号序列 → 状态转移图
  （节点=去重状态，边=顺序转移+计数，初始/终态标注）；
- build_learning_graph：学习管道图（session→window→semantic→align→skill，
  审计 trace 图化）；
- build_canvas_flow：画布/流水线图，replay_batch 节点展开 skill 子图
  （点"批量测试"不再跳套件页，图内下钻）。
"""
import json

import pytest


@pytest.fixture
def seeded_flow_data(client):
    """两轮录制含状态序列（active→resolved→closed）+ 对齐产技能。"""
    async def _seed():
        out = {}
        for rnd, (v1, v2) in enumerate([("active", "resolved"), ("active", "resolved")]):
            sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
            out[f"sid{rnd}"] = sid
            events = [
                {"seq": 0, "ts": 0, "kind": "navigation",
                 "payload": {"type": "page-load", "url": "http://mock.local/"}},
                {"seq": 1, "ts": 100, "kind": "action",
                 "payload": {"type": "click", "target": {"label": "解决"}},
                             "url": "http://mock.local/bug"},
                {"seq": 2, "ts": 300, "kind": "network",
                 "payload": {"method": "POST", "url": "/bug/1/resolve",
                             "status": 200, "reqBody": "{}",
                             "resBody": json.dumps({"result": "success",
                                                    "status": v1})}},
                {"seq": 3, "ts": 2000, "kind": "action",
                 "payload": {"type": "click", "target": {"label": "关闭"}},
                             "url": "http://mock.local/bug"},
                {"seq": 4, "ts": 2200, "kind": "network",
                 "payload": {"method": "POST", "url": "/bug/1/close",
                             "status": 200, "reqBody": "{}",
                             "resBody": json.dumps({"result": "success",
                                                    "status": v2})}},
            ]
            assert (await client.post(f"/api/v1/sessions/{sid}/events",
                                      json=events)).status_code == 200
            await client.post(f"/api/v1/sessions/{sid}/process")
        aid = (await client.post("/api/v1/align", json={
            "session_ids": [out["sid0"], out["sid1"]]})).json()["alignment_id"]
        out["aid"] = aid
        skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
        out["skill"] = skill
        return out
    return _seed


async def test_build_state_machine(seeded_flow_data, client):
    """状态机归纳：多轮录制的状态信号 → 转移图（去重节点+计数边）。"""
    from app.db import SessionLocal
    from app.replay.flow_graph import build_state_machine
    data = await seeded_flow_data()
    db = SessionLocal()
    try:
        sm = build_state_machine(db, data["skill"]["id"])
    finally:
        db.close()
    labels = {n["label"] for n in sm["nodes"]}
    assert "status=active" in labels
    assert "status=resolved" in labels
    # 评审#5：节点 id=复合键 field=value（裸 value 会让同值不同字段并点）
    ids = {n["id"] for n in sm["nodes"]}
    assert "status=active" in ids and "status=resolved" in ids
    # 转移边 active→resolved 出现两轮 → 计数 2
    edge = next(e for e in sm["edges"]
                if e["from"] == "status=active" and e["to"] == "status=resolved")
    assert edge["count"] == 2
    # active 是 status 流初始态（无入边）、resolved 是其终态（无出边）
    assert "status=active" in sm["initial"]
    assert "status=resolved" in sm["final"]
    # 常量信号（result=success 每步相同）无转移边，孤点不进 initial/final 误判
    assert "status=resolved" not in sm["initial"]


async def test_build_learning_graph(seeded_flow_data, client):
    """学习图：审计 trace 图化 session→window→semantic→align→skill。"""
    from app.db import SessionLocal
    from app.replay.flow_graph import build_learning_graph
    await seeded_flow_data()
    db = SessionLocal()
    try:
        g = build_learning_graph(db)
    finally:
        db.close()
    types = {n["type"] for n in g["nodes"]}
    assert {"session", "window", "semantic", "align", "skill"} <= types
    # 至少一条完整链：session→window→semantic→align→skill
    sem_nodes = [n for n in g["nodes"] if n["type"] == "semantic"]
    assert sem_nodes, "语义动作节点缺失"
    assert any("解决" in (n["label"] or "") for n in sem_nodes)


async def test_build_canvas_flow_subgraph(client):
    """画布子图：replay_batch 节点展开其 skill_source 子技能子图。
    skill_ids 兼容两种存放：config（编辑器保存）/ params（套件生成）。"""
    from app.replay.flow_graph import build_canvas_flow
    dag = {"nodes": [
        {"id": "src", "type": "skill_source", "label": "技能源",
         "params": {"skill_ids": [107, 111]}},
        {"id": "batch", "type": "replay_batch", "label": "批量测试"},
        {"id": "agg", "type": "aggregate", "label": "汇总"},
    ], "edges": [
        {"from": "src", "to": "batch"}, {"from": "batch", "to": "agg"}]}
    flow = build_canvas_flow(dag)
    types = [n["type"] for n in flow["nodes"]]
    assert "skill_source" in types and "replay_batch" in types
    # 子图节点：batch 展开挂两个 skill 子节点
    sub = [n for n in flow["nodes"] if n.get("sub_of") == "batch"]
    assert len(sub) == 2
    assert all(n["type"] == "skill" for n in sub)
    # 子节点边连到 batch
    assert all(any(e["from"] == n["id"] and e["to"] == "batch"
                   for e in flow["edges"]) for n in sub)


async def test_skill_state_machine_endpoint(seeded_flow_data, client):
    """GET /skills/{id}/state-machine：状态机归纳端点。"""
    data = await seeded_flow_data()
    resp = await client.get(f"/api/v1/skills/{data['skill']['id']}/state-machine")
    assert resp.status_code == 200
    body = resp.json()
    assert any(n["label"] == "status=active" for n in body["nodes"])
    assert "status=active" in body["initial"]


async def test_state_machine_fields_do_not_collide(client):
    """评审#5：status=1 与 docstatus=1 曾并为同一节点（id=裸 value，首个
    label 胜、两字段转移画在一个节点上）——复合键后是两个独立节点、
    各自独立边；field/value 以新增属性下发（响应契约不变）。"""
    from app.db import SessionLocal
    from app.models import Alignment, SemanticAction, Skill
    from app.replay.flow_graph import build_state_machine
    db = SessionLocal()
    try:
        skeleton = [
            {"signature": "click:提交", "session_window_seqs": {"sA": 0}},
            {"signature": "click:审核", "session_window_seqs": {"sA": 1}},
        ]
        al = Alignment(session_ids=["sA"], skeleton=skeleton,
                       param_variables=[], input_variables=[])
        db.add(al)
        db.flush()
        db.add(SemanticAction(session_id="sA", window_seq=0, anchor_seq=0,
                              anchor_type="click", target={"label": "提交"},
                              api_calls=[], state_signals=[
                                  {"field": "status", "value": 1},
                                  {"field": "docstatus", "value": 0}]))
        db.add(SemanticAction(session_id="sA", window_seq=1, anchor_seq=1,
                              anchor_type="click", target={"label": "审核"},
                              api_calls=[], state_signals=[
                                  {"field": "status", "value": 2},
                                  {"field": "docstatus", "value": 1}]))
        sk = Skill(alignment_id=al.id, name="n", description="d",
                   status="learned", skeleton=skeleton,
                   param_variables=[], input_variables=[],
                   confidence=1.0, evidence_count=1)
        db.add(sk)
        db.commit()
        sm = build_state_machine(db, sk.id)
    finally:
        db.close()
    by_id = {n["id"]: n for n in sm["nodes"]}
    # 同值 1 的两个字段状态是不同节点
    assert "status=1" in by_id and "docstatus=1" in by_id
    assert by_id["status=1"]["label"] == "status=1"
    assert by_id["docstatus=1"]["label"] == "docstatus=1"
    assert by_id["status=1"]["field"] == "status"
    assert by_id["docstatus=1"]["field"] == "docstatus"
    assert by_id["status=1"]["value"] == "1"
    # 各字段转移独立成边，无跨字段串边
    edge_set = {(e["from"], e["to"]) for e in sm["edges"]}
    assert ("status=1", "status=2") in edge_set
    assert ("docstatus=0", "docstatus=1") in edge_set
    assert len(edge_set) == 2
    assert sm["initial"] == ["docstatus=0", "status=1"]
    assert sm["final"] == ["docstatus=1", "status=2"]


async def test_learning_graph_endpoint(client):
    """GET /learning-graph：学习图端点（无数据 200 空图）。"""
    resp = await client.get("/api/v1/learning-graph")
    assert resp.status_code == 200
    assert "nodes" in resp.json()


async def test_canvas_flow_endpoint(client):
    """GET /canvas/{id}/flow：画布图（含子图展开）。"""
    dag = {"nodes": [
        {"id": "src", "type": "skill_source", "label": "技能源",
         "config": {"skill_ids": [107, 111]}},
        {"id": "batch", "type": "replay_batch", "label": "批量测试"},
        {"id": "agg", "type": "aggregate", "label": "汇总"},
    ], "edges": [
        {"from": "src", "to": "batch"}, {"from": "batch", "to": "agg"}]}
    from app.db import SessionLocal
    from app.models import CanvasDag
    db = SessionLocal()
    try:
        row = CanvasDag(name="测试流水线", dag=dag)
        db.add(row)
        db.commit()
        db.refresh(row)
        cid = row.id
    finally:
        db.close()
    resp = await client.get(f"/api/v1/canvas/{cid}/flow")
    assert resp.status_code == 200
    body = resp.json()
    sub = [n for n in body["nodes"] if n.get("sub_of") == "batch"]
    assert len(sub) == 2
