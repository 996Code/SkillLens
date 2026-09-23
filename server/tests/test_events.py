async def test_batch_ingest(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 1, "ts": 1700000000000, "kind": "action",
         "payload": {"type": "click", "target": "button", "label": "提交"}},
        {"seq": 2, "ts": 1700000000120, "kind": "network",
         "payload": {"method": "POST", "url": "/api/order/92382/submit", "status": 200}},
    ]
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 2}


async def test_rejects_bad_kind(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    resp = await client.post(
        f"/api/v1/sessions/{sid}/events",
        json=[{"seq": 1, "ts": 1, "kind": "bogus", "payload": {}}],
    )
    assert resp.status_code == 422


async def test_rejects_duplicate_seq(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = [{"seq": 1, "ts": 1, "kind": "action", "payload": {}}]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    assert resp.status_code == 409  # 重复 (session_id, seq) 拒绝
