async def test_create_session(client):
    resp = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["session_id"]) == 36  # uuid
    # 幂等性不要求，但重复调用应产生不同 session
    resp2 = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp2.json()["session_id"] != body["session_id"]
