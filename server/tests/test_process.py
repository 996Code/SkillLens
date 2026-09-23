async def _seed(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 900, "kind": "network",
         "payload": {"method": "GET", "url": "/codeBack/role/list", "status": 200,
                     "duration": 52, "reqBody": None, "resBody": '{"code":200}'}},
        {"seq": 2, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "duration": 74, "reqBody": "{}",
                     "resBody": '{"code":200,"status":"SUCCESS"}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    return sid


async def test_process_creates_semantic_actions(client):
    sid = await _seed(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    assert resp.json() == {"windows": 1}

    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["anchor_type"] == "click"
    assert row["target"]["label"] == "保存"
    assert [c["template"] for c in row["api_calls"]] == ["/codeBack/formConfig/saveFormConfig"]
    assert row["api_calls"][0]["method"] == "POST"
    assert row["state_signals"] == [{"api": "/codeBack/formConfig/saveFormConfig",
                                     "field": "code", "value": 200},
                                    {"api": "/codeBack/formConfig/saveFormConfig",
                                     "field": "status", "value": "SUCCESS"}]


async def test_process_idempotent(client):
    sid = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid}/process")
    await client.post(f"/api/v1/sessions/{sid}/process")  # 重算不重复
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1


async def test_process_404(client):
    resp = await client.post("/api/v1/sessions/nonexistent/process")
    assert resp.status_code == 404


async def test_intermediate_tables_written(client):
    sid = await _seed(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    dump = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(dump) == 1

    from app.db import SessionLocal
    from app.models import NormalizedEvent, TransactionWindow
    from sqlalchemy import select
    db = SessionLocal()
    try:
        nes = db.execute(select(NormalizedEvent).where(NormalizedEvent.session_id == sid)).scalars().all()
        tws = db.execute(select(TransactionWindow).where(TransactionWindow.session_id == sid)).scalars().all()
        assert len(tws) == 1
        assert tws[0].idle_ms == 2000 and tws[0].max_window_ms == 8000
        assert len(tws[0].member_event_ids) == 1  # 只有锚点后的 POST
        templates = {ne.template for ne in nes}
        assert "click:保存" in templates
        assert "POST:/codeBack/formConfig/saveFormConfig" in templates
        assert "GET:/codeBack/role/list" in templates
    finally:
        db.close()


async def test_intermediate_idempotent(client):
    sid = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid}/process")
    await client.post(f"/api/v1/sessions/{sid}/process")
    from app.db import SessionLocal
    from app.models import NormalizedEvent, TransactionWindow
    from sqlalchemy import select
    db = SessionLocal()
    try:
        assert len(db.execute(select(NormalizedEvent).where(NormalizedEvent.session_id == sid)).scalars().all()) == 4
        assert len(db.execute(select(TransactionWindow).where(TransactionWindow.session_id == sid)).scalars().all()) == 1
    finally:
        db.close()
