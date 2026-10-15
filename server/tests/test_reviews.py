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


async def test_pending_queue_targets_ready_unreviewed_reports(client):
    """AR4：待评审队列 = ready 且未评审的场景报告（AgentRun 队列退役）。"""
    from app.db import SessionLocal
    from app.models import ScenarioReport, ScenarioRun

    db = SessionLocal()
    try:
        run = ScenarioRun(scenario_id=1, definition_version=1,
                          definition_snapshot={"root": {}, "steps": []},
                          executor="server", mode="execute", status="pass",
                          confirm_side_effect=True,
                          idempotency_key="ar4-pending-1",
                          request_fingerprint="f" * 64)
        db.add(run)
        db.flush()
        rep = ScenarioReport(scenario_run_id=run.id, status="ready",
                             coverage_state="no_expectation")
        db.add(rep)
        db.commit()
        db.refresh(rep)
        rep_id, run_id = rep.id, run.id
    finally:
        db.close()

    items = (await client.get("/api/v1/reviews/pending")).json()
    match = [i for i in items if i["report_id"] == rep_id]
    assert match and match[0]["scenario_run_id"] == run_id


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
