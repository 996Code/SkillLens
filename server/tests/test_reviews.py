"""S15 I1 评审门户后端：POST/GET /api/v1/reviews + GET /api/v1/reviews/pending。

- POST /reviews：decision 枚举校验（422）/ agent_run 不存在 404 /
  同 run 重复评审 409 / 201 返回评审行（含 agent_run 摘要）；
- GET /reviews?decision=：倒序列表（含 agent_run 摘要 graph_name/status/started_at）；
- GET /reviews/pending：未评审的 agent_run 列表（node_outputs 摘要——
  含 review_output 段若有），已评审的 run 不出现。
"""
import json


def _add_agent_run(graph_name="nightly", status="finished", node_outputs=None) -> int:
    """直接落 agent_run 行（评审门户评审的是夜间运行记录，不依赖图执行）。"""
    from app.db import SessionLocal
    from app.models import AgentRun
    db = SessionLocal()
    try:
        run = AgentRun(graph_name=graph_name, input={},
                       node_outputs=node_outputs if node_outputs is not None else [],
                       status=status)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_create_review_and_list(client):
    run1 = _add_agent_run()
    run2 = _add_agent_run(graph_name="canvas", status="error")

    resp = await client.post("/api/v1/reviews", json={
        "agent_run_id": run1, "reviewer": "alice",
        "decision": "approved", "comment": "夜间回归全绿，放行"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["agent_run_id"] == run1
    assert body["reviewer"] == "alice"
    assert body["decision"] == "approved"
    assert body["comment"] == "夜间回归全绿，放行"
    assert body["id"] > 0 and body["created_at"]
    # agent_run 摘要
    assert body["agent_run"]["graph_name"] == "nightly"
    assert body["agent_run"]["status"] == "finished"
    assert body["agent_run"]["started_at"]

    resp = await client.post("/api/v1/reviews", json={
        "agent_run_id": run2, "reviewer": "bob", "decision": "changes_requested"})
    assert resp.status_code == 201
    assert resp.json()["comment"] is None          # comment 可省略

    # 列表倒序（新评审在前），含 agent_run 摘要
    items = (await client.get("/api/v1/reviews")).json()
    assert [i["agent_run_id"] for i in items] == [run2, run1]
    assert items[0]["decision"] == "changes_requested"
    assert items[1]["agent_run"]["graph_name"] == "nightly"

    # decision 过滤
    approved = (await client.get("/api/v1/reviews?decision=approved")).json()
    assert [i["agent_run_id"] for i in approved] == [run1]
    rejected = (await client.get("/api/v1/reviews?decision=rejected")).json()
    assert rejected == []


async def test_create_review_invalid_decision_422(client):
    run = _add_agent_run()
    resp = await client.post("/api/v1/reviews", json={
        "agent_run_id": run, "reviewer": "alice", "decision": "maybe"})
    assert resp.status_code == 422
    # GET 过滤参数同样枚举校验
    resp = await client.get("/api/v1/reviews?decision=maybe")
    assert resp.status_code == 422


async def test_create_review_missing_run_404(client):
    resp = await client.post("/api/v1/reviews", json={
        "agent_run_id": 99999, "reviewer": "alice", "decision": "approved"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "agent_run not found"


async def test_create_review_duplicate_409(client):
    run = _add_agent_run()
    body = {"agent_run_id": run, "reviewer": "alice", "decision": "approved"}
    assert (await client.post("/api/v1/reviews", json=body)).status_code == 201
    resp = await client.post("/api/v1/reviews", json={
        **body, "reviewer": "bob", "decision": "rejected"})
    assert resp.status_code == 409
    assert "已评审" in resp.json()["detail"]


async def test_pending_excludes_reviewed(client):
    reviewed = _add_agent_run()
    node_outputs = [
        {"node": "select_skills", "output": {"skills": [1]}},
        {"node": "review_output", "output": {"review": "# 夜间回归摘要\n- 全绿"}},
    ]
    pending_run = _add_agent_run(graph_name="canvas", node_outputs=node_outputs)

    await client.post("/api/v1/reviews", json={
        "agent_run_id": reviewed, "reviewer": "alice", "decision": "approved"})

    items = (await client.get("/api/v1/reviews/pending")).json()
    assert [i["id"] for i in items] == [pending_run]   # 已评审的不在队列
    item = items[0]
    assert set(item) == {"id", "graph_name", "status", "started_at", "node_outputs"}
    assert item["graph_name"] == "canvas"
    assert item["status"] == "finished"
    # node_outputs 摘要透传——评审页据此渲染 review_output 段
    assert [seg["node"] for seg in item["node_outputs"]] == \
        ["select_skills", "review_output"]
    assert item["node_outputs"][1]["output"]["review"].startswith("# 夜间回归摘要")


async def test_pending_empty(client):
    assert (await client.get("/api/v1/reviews/pending")).json() == []
