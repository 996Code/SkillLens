async def _seed_session(client, order_id: int) -> str:
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "input", "name": "订单名", "value": f"订单-{order_id}"}},
        {"seq": 2, "ts": 2000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 2600, "kind": "network",
         "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                     "status": 200, "duration": 50, "reqBody": "{}",
                     "resBody": '{"code":200,"status":"SUCCESS"}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    assert (await client.post(f"/api/v1/sessions/{sid}/process")).status_code == 200
    return sid


async def test_align_two_sessions(client):
    s1 = await _seed_session(client, 111)
    s2 = await _seed_session(client, 222)
    resp = await client.post("/api/v1/align", json={"session_ids": [s1, s2]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alignment_id"] > 0
    sigs = [s["signature"] for s in body["skeleton"]]
    assert sigs == ["click:保存|POST:/orders/{id}/save"]
    assert body["param_variables"] == [{"step": "click:保存|POST:/orders/{id}/save",
                                        "param": "id_0", "values": {s1: "111", s2: "222"}}]
    assert body["input_variables"][0]["name"] == "订单名"
    assert body["input_variables"][0]["values"] == {s1: "订单-111", s2: "订单-222"}

    got = await client.get(f"/api/v1/alignments/{body['alignment_id']}")
    assert got.status_code == 200
    assert got.json()["skeleton"] == body["skeleton"]


async def test_align_unknown_session_404(client):
    # 同 R1 类缺陷：单元素会被 min_length=2 拦成 422，传两个以触发 404 分支
    resp = await client.post("/api/v1/align", json={"session_ids": ["nope", "nope2"]})
    assert resp.status_code == 404


async def test_align_unprocessed_409(client):
    # 控制器裁定 R1：传两个空 session（单 sid 会被 min_length=2 拦成 422）
    s1 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    s2 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    resp = await client.post("/api/v1/align", json={"session_ids": [s1, s2]})
    assert resp.status_code == 409


async def test_alignment_get_404(client):
    resp = await client.get("/api/v1/alignments/99999")
    assert resp.status_code == 404
