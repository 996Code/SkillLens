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
    assert resp.json()["accepted"] == 2


async def test_rejects_bad_kind(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    resp = await client.post(
        f"/api/v1/sessions/{sid}/events",
        json=[{"seq": 1, "ts": 1, "kind": "bogus", "payload": {}}],
    )
    assert resp.status_code == 422


async def test_duplicate_seq_idempotent_skip(client):
    """评审 #5：重复 (session,page,seq) 跳过而非 409——幂等重发安全，
    一条旧 seq 不再让整批事件永久丢失。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = [{"seq": 1, "ts": 1, "kind": "action", "payload": {}}]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"accepted": 0, "duplicates": 1}


async def test_partial_batch_duplicate_rest_saved(client):
    """混合批：旧 seq+新 seq 同批——旧的跳过，新的必须落库（旧实现整批 409 全丢）。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    await client.post(f"/api/v1/sessions/{sid}/events", json=[
        {"seq": 1, "ts": 1, "kind": "action", "payload": {}}])
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=[
        {"seq": 1, "ts": 1, "kind": "action", "payload": {}},   # 旧
        {"seq": 2, "ts": 2, "kind": "action", "payload": {}},   # 新
    ])
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 1, "duplicates": 1}


async def test_same_seq_different_page_accepted(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = {"seq": 1, "ts": 1, "kind": "action", "payload": {}}
    r1 = await client.post(f"/api/v1/sessions/{sid}/events", json=[{**ev, "page_id": "page-a"}])
    r2 = await client.post(f"/api/v1/sessions/{sid}/events", json=[{**ev, "page_id": "page-b"}])
    assert r1.status_code == 200 and r2.status_code == 200  # 跨页同 seq 不再冲突


async def test_ingest_guard_blocks_foreign_origin(client):
    """评审 #4：CORS * 叠加豁免鉴权——无 X-SkillLens-Agent 头的调用
    （网页跨域伪造）必须 403；带头（插件）正常。"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as bare:
        r = await bare.post("/api/v1/sessions", json={})
        assert r.status_code == 403
        r2 = await bare.post("/api/v1/sessions", json={},
                             headers={"X-SkillLens-Agent": "1"})
        assert r2.status_code == 200


async def test_oversized_batch_rejected(client):
    """三轮评审：批量无上限。逐条 commit 的实现下，一个超大请求能把 worker
    钉死几分钟并写入任意多行（本端点豁免鉴权，任何本机网页都能打）。
    上限 413 拒绝，插件侧 BATCH=50 有 40x 余量。"""
    from app.api.events import MAX_EVENTS_PER_BATCH
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = [{"seq": i, "ts": i, "kind": "action", "payload": {}}
          for i in range(1, MAX_EVENTS_PER_BATCH + 2)]
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    assert resp.status_code == 413
    assert str(MAX_EVENTS_PER_BATCH) in resp.json()["detail"]


def test_batch_limit_has_headroom_over_client_batch():
    """上限不得低于插件批量的 10x——否则正常录制会被自己的服务端拒收。"""
    from app.api.events import MAX_EVENTS_PER_BATCH
    assert MAX_EVENTS_PER_BATCH >= 500
