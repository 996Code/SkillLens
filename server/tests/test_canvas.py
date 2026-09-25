"""S14 Task 1（块 H2）：canvas_dag 表 + DAG 校验/编译器。

- validate_dag：合法线性链通过；环/未知类型/缺参/分叉超限拒绝；
- POST /api/v1/canvas：validate 通过才存（版本化——每次保存新行）；
- GET /api/v1/canvas 列表（倒序）/ GET /api/v1/canvas/{id} 详情（含 dag）。
"""
import pytest

VALID_DAG = {
    "nodes": [
        {"id": "n1", "type": "change_source",
         "params": {"api_templates": ["/x/save"]}, "x": 0, "y": 0},
        {"id": "n2", "type": "impact_select", "params": {}, "x": 200, "y": 0},
        {"id": "n3", "type": "replay_batch", "params": {}, "x": 400, "y": 0},
        {"id": "n4", "type": "aggregate", "params": {}, "x": 600, "y": 0},
        {"id": "n5", "type": "review_output", "params": {}, "x": 800, "y": 0},
    ],
    "edges": [
        {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"},
        {"from": "n3", "to": "n4"}, {"from": "n4", "to": "n5"},
    ],
}


def _dag(nodes, edges):
    return {"nodes": nodes, "edges": edges}


# ---------- validate_dag（纯函数） ----------

def test_validate_dag_accepts_valid_chain():
    from app.agents.canvas import validate_dag
    ok, errors = validate_dag(VALID_DAG)
    assert ok is True and errors == []


def test_validate_dag_accepts_single_merge():
    """v1 允许链尾汇聚：两条链汇入同一 aggregate（入度 2 ≤ 上限）。"""
    from app.agents.canvas import validate_dag
    dag = _dag(
        [{"id": "a", "type": "change_source",
          "params": {"anchor_labels": ["保存"]}, "x": 0, "y": 0},
         {"id": "b", "type": "impact_select", "params": {}, "x": 0, "y": 200},
         {"id": "c", "type": "aggregate", "params": {}, "x": 400, "y": 100}],
        [{"from": "a", "to": "c"}, {"from": "b", "to": "c"}])
    ok, errors = validate_dag(dag)
    assert ok is True, errors


def test_validate_dag_rejects_cycle():
    from app.agents.canvas import validate_dag
    dag = _dag(
        [{"id": "n1", "type": "impact_select", "params": {}},
         {"id": "n2", "type": "aggregate", "params": {}}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n1"}])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("环" in e for e in errors), errors


def test_validate_dag_rejects_unknown_type():
    from app.agents.canvas import validate_dag
    dag = _dag([{"id": "n1", "type": "magic_wand", "params": {}}], [])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("未知节点类型" in e for e in errors), errors


def test_validate_dag_rejects_duplicate_ids():
    from app.agents.canvas import validate_dag
    dag = _dag([{"id": "n1", "type": "aggregate", "params": {}},
                {"id": "n1", "type": "aggregate", "params": {}}], [])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("重复" in e for e in errors), errors


def test_validate_dag_rejects_edge_to_missing_node():
    from app.agents.canvas import validate_dag
    dag = _dag([{"id": "n1", "type": "aggregate", "params": {}}],
               [{"from": "n1", "to": "ghost"}])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("ghost" in e for e in errors), errors


def test_validate_dag_rejects_change_source_without_params():
    """change_source 必填：api_templates 或 anchor_labels 至少一个非空数组。"""
    from app.agents.canvas import validate_dag
    dag = _dag([{"id": "n1", "type": "change_source", "params": {}}], [])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("change_source" in e for e in errors), errors


def test_validate_dag_rejects_fork():
    """分叉超限：出度 >1 → v1 仅支持线性链。"""
    from app.agents.canvas import validate_dag
    dag = _dag(
        [{"id": "n1", "type": "change_source",
          "params": {"api_templates": ["/x"]}, "x": 0, "y": 0},
         {"id": "n2", "type": "impact_select", "params": {}},
         {"id": "n3", "type": "aggregate", "params": {}}],
        [{"from": "n1", "to": "n2"}, {"from": "n1", "to": "n3"}])
    ok, errors = validate_dag(dag)
    assert ok is False
    assert any("v1 仅支持线性链" in e for e in errors), errors


def test_validate_dag_rejects_empty_nodes():
    from app.agents.canvas import validate_dag
    ok, errors = validate_dag({"nodes": [], "edges": []})
    assert ok is False and errors


# ---------- 端点：保存版本化 / 列表 / 详情 ----------

async def test_canvas_save_versioned(client):
    """两次保存 → 两行（版本化不覆盖），id 递增，列表倒序。"""
    r1 = await client.post("/api/v1/canvas", json={"name": "流水线 v1", "dag": VALID_DAG})
    assert r1.status_code == 201, r1.text
    r2 = await client.post("/api/v1/canvas", json={"name": "流水线 v2", "dag": VALID_DAG})
    assert r2.status_code == 201
    id1, id2 = r1.json()["id"], r2.json()["id"]
    assert id2 > id1  # 新行而非覆盖

    lst = await client.get("/api/v1/canvas")
    assert lst.status_code == 200
    items = lst.json()
    assert [it["id"] for it in items] == [id2, id1]  # 倒序
    assert set(items[0]) == {"id", "name", "created_at"}

    detail = await client.get(f"/api/v1/canvas/{id1}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["name"] == "流水线 v1"
    assert body["dag"] == VALID_DAG  # dag 原样存取


async def test_canvas_save_rejects_invalid_dag(client):
    """validate 不通过 → 422 不入库。"""
    bad = _dag([{"id": "n1", "type": "no_such_type", "params": {}}], [])
    resp = await client.post("/api/v1/canvas", json={"name": "坏画布", "dag": bad})
    assert resp.status_code == 422
    lst = await client.get("/api/v1/canvas")
    assert lst.json() == []


async def test_canvas_detail_404(client):
    resp = await client.get("/api/v1/canvas/999")
    assert resp.status_code == 404


# ---------- Task 2：运行 + 历史 + 预置 seed ----------

async def _seed_skill(client, monkeypatch) -> int:
    """FakeProvider 真管道：1 skill + evidence（保存请求打在预置模板上，
    使预置画布的 change_source 能 impact 命中）。"""
    import json
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align",
                            json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"]


def _db():
    from app.db import SessionLocal
    return SessionLocal()


async def test_preset_canvas_run_end_to_end(client, monkeypatch):
    """预置"定向回归流水线"：ensure_preset 空库播种 → POST run →
    agent_run finished、node_outputs 5 段、replay 段 shadow、runs 列表含它。"""
    skill_id = await _seed_skill(client, monkeypatch)
    from app.agents.canvas import ensure_preset
    from app.models import AgentRun

    db = _db()
    try:
        preset = ensure_preset(db)
        assert preset is not None and preset.name == "定向回归流水线"
        # 再调一次不重复播种（canvas_dag 非空）
        assert ensure_preset(db).id == preset.id

        resp = await client.post(f"/api/v1/canvas/{preset.id}/run")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "finished"
        assert body["graph_name"] == f"canvas:{preset.id}"
        segs = body["node_outputs"]
        assert [s["node"] for s in segs] == ["n1", "n2", "n3", "n4", "n5"]
        assert len(segs) == 5

        # impact 段：预置模板命中 seeded skill
        assert segs[1]["output"]["skills"] == [skill_id]
        # replay 段：C1 默认 shadow（写请求骨架未 confirm）
        replay = segs[2]["output"]["replay_results"]
        assert replay[0]["skill_id"] == skill_id
        assert replay[0]["status"] == "shadow"
        assert replay[0]["run_id"] > 0
        # aggregate 段
        assert segs[3]["output"]["aggregate"] == {"shadow": 1, "total": 1}
        # review 段：markdown 摘要含变更集/受影响 skill/回放统计
        review = segs[4]["output"]["review"]
        assert "# 画布运行摘要" in review
        assert "受影响 skill：1 个" in review
        assert "shadow=1" in review

        # agent_run 落库：input 记 canvas_id（C3）
        run = db.get(AgentRun, body["id"])
        assert run.input == {"canvas_id": preset.id}
        assert run.status == "finished" and run.error_text is None

        # runs 列表含该 run（graph_name 前缀过滤）
        runs = await client.get(f"/api/v1/canvas/{preset.id}/runs")
        assert runs.status_code == 200
        items = runs.json()
        assert items[0]["id"] == body["id"]
        assert items[0]["status"] == "finished"
        assert items[0]["node_count"] == 5
        assert items[0]["finished_at"] is not None
    finally:
        db.close()


async def test_canvas_run_confirm_defaults_false(client, monkeypatch):
    """C1：replay_batch 节点未写 confirm_side_effect → 编译期默认 False → shadow。"""
    await _seed_skill(client, monkeypatch)
    dag = _dag(
        [{"id": "n1", "type": "change_source",
          "params": {"api_templates": ["/codeBack/formConfig/saveFormConfig"]},
          "x": 0, "y": 0},
         {"id": "n2", "type": "impact_select", "params": {}, "x": 200, "y": 0},
         {"id": "n3", "type": "replay_batch", "params": {}, "x": 400, "y": 0}],
        [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}])
    cid = (await client.post("/api/v1/canvas",
                             json={"name": "无 confirm 画布", "dag": dag})
           ).json()["id"]
    resp = await client.post(f"/api/v1/canvas/{cid}/run")
    segs = resp.json()["node_outputs"]
    assert segs[2]["output"]["replay_results"][0]["status"] == "shadow"


async def test_canvas_run_404(client):
    resp = await client.post("/api/v1/canvas/999/run")
    assert resp.status_code == 404
    resp = await client.get("/api/v1/canvas/999/runs")
    assert resp.status_code == 404


# ---------- Task 3：agent_run 详情轻端点（前端着色/产物下钻用） ----------

async def test_canvas_run_detail_endpoint(client, monkeypatch):
    """GET /api/v1/canvas/runs/{agent_run_id} → run 详情（着色/产物下钻）。
    404：不存在的 run。"""
    await _seed_skill(client, monkeypatch)
    from app.agents.canvas import ensure_preset

    db = _db()
    try:
        preset = ensure_preset(db)
        run_id = (await client.post(
            f"/api/v1/canvas/{preset.id}/run")).json()["id"]

        resp = await client.get(f"/api/v1/canvas/runs/{run_id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body) == {"id", "status", "node_outputs", "input",
                             "error_text"}
        assert body["id"] == run_id
        assert body["status"] == "finished"
        assert body["input"] == {"canvas_id": preset.id}
        assert body["error_text"] is None
        assert [s["node"] for s in body["node_outputs"]] == [
            "n1", "n2", "n3", "n4", "n5"]

        assert (await client.get("/api/v1/canvas/runs/999")
                ).status_code == 404
    finally:
        db.close()


async def test_canvas_runs_only_own_canvas(client, monkeypatch):
    """runs 列表按 graph_name 前缀隔离：nightly 图的 run 不混入。"""
    await _seed_skill(client, monkeypatch)
    from app.agents.canvas import ensure_preset
    from app.agents.runtime import run_graph
    from app.models import AgentRun

    db = _db()
    try:
        await run_graph(db, "nightly", {"change_set": {}})
        preset = ensure_preset(db)
        runs = await client.get(f"/api/v1/canvas/{preset.id}/runs")
        assert runs.json() == []  # 无 canvas run，nightly 不计入
        assert db.query(AgentRun).filter(
            AgentRun.graph_name == "nightly").count() == 1
    finally:
        db.close()
