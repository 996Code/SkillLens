"""AR1 freezes AgentRun review writes; legacy reads remain auditable."""


def _add_agent_run(graph_name="nightly", status="finished", node_outputs=None) -> int:
    from app.db import SessionLocal
    from app.models import AgentRun

    db = SessionLocal()
    try:
        run = AgentRun(graph_name=graph_name, input={},
                       node_outputs=node_outputs or [], status=status)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_legacy_review_write_is_frozen(client):
    run_id = _add_agent_run()
    response = await client.post("/api/v1/reviews", json={
        "agent_run_id": run_id,
        "decision": "approved",
        "comment": "旧评审",
    })
    assert response.status_code == 410
    assert "AR1" in response.json()["detail"]


async def test_legacy_reviews_remain_readable(client):
    from app.db import SessionLocal
    from app.models import Review

    run_id = _add_agent_run()
    db = SessionLocal()
    try:
        row = Review(agent_run_id=run_id, reviewer="历史评审人",
                     user_id=None, decision="approved", comment="已归档")
        db.add(row)
        db.commit()
        db.refresh(row)
        review_id = row.id
    finally:
        db.close()

    items = (await client.get("/api/v1/reviews")).json()
    item = next(value for value in items if value["id"] == review_id)
    assert item["agent_run_id"] == run_id
    assert item["reviewer"] == "历史评审人"
    assert item["agent_run"]["status"] == "finished"


async def test_pending_agent_runs_remain_readable(client):
    pending_id = _add_agent_run(
        graph_name="canvas",
        node_outputs=[{"node": "review_output", "output": {"review": "摘要"}}],
    )
    items = (await client.get("/api/v1/reviews/pending")).json()
    assert any(item["id"] == pending_id for item in items)


async def test_viewer_cannot_call_frozen_review_write(client):
    from app.auth import create_user, issue_token
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        user = create_user(db, "ar1-review-viewer", "pw", "viewer")
        token = issue_token(db, user.id)
    finally:
        db.close()
    response = await client.post(
        "/api/v1/reviews",
        headers={"Authorization": f"Bearer {token}"},
        json={"agent_run_id": _add_agent_run(), "decision": "approved"},
    )
    assert response.status_code == 403
