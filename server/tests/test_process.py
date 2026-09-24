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
    assert resp.json() == {"windows": 1, "kept": 1}  # S10：噪声过滤后 kept 计数

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


async def _seed_with_snapshots(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        # before 快照：锚点动作前同步采集（ts 略早于 action）
        {"seq": 1, "ts": 950, "kind": "snapshot",
         "payload": {"phase": "before",
                     "forms": [{"label": "表单名", "value": "默认A"}],
                     "labels": [{"text": "草稿"}], "tables": []}},
        {"seq": 2, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "duration": 74, "reqBody": "{}",
                     "resBody": '{"code":200,"status":"SUCCESS"}'}},
        # after 快照：锚点后 2.5s 采集
        {"seq": 4, "ts": 4200, "kind": "snapshot",
         "payload": {"phase": "after",
                     "forms": [{"label": "表单名", "value": "默认B"}],
                     "labels": [{"text": "已发布"}], "tables": [],
                     "overflow": False}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    return sid


async def test_process_semantic_state_from_snapshots(client):
    sid = await _seed_with_snapshots(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["state_before"]["phase"] == "before"
    assert row["state_before"]["forms"][0]["value"] == "默认A"
    assert row["state_after"]["phase"] == "after"
    assert row["state_after"]["forms"][0]["value"] == "默认B"
    # 窗口产物不受快照事件污染：api_calls 仍只含网络请求
    assert [c["template"] for c in row["api_calls"]] == ["/codeBack/formConfig/saveFormConfig"]


async def test_process_without_snapshots_state_null(client):
    sid = await _seed(client)  # 旧式事件流，无 snapshot
    await client.post(f"/api/v1/sessions/{sid}/process")
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1
    assert rows[0]["state_before"] is None
    assert rows[0]["state_after"] is None


async def test_process_multiple_after_snapshots_takes_last(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 950, "kind": "snapshot",
         "payload": {"phase": "before", "forms": [{"label": "f", "value": "v0"}],
                     "labels": [], "tables": []}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 2, "ts": 3000, "kind": "snapshot",
         "payload": {"phase": "after", "forms": [{"label": "f", "value": "v1"}],
                     "labels": [], "tables": []}},
        # 重渲染触发的第二个 after：取最后
        {"seq": 3, "ts": 5000, "kind": "snapshot",
         "payload": {"phase": "after", "forms": [{"label": "f", "value": "v2"}],
                     "labels": [], "tables": []}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert rows[0]["state_before"]["forms"][0]["value"] == "v0"
    assert rows[0]["state_after"]["forms"][0]["value"] == "v2"
