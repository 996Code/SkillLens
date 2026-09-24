async def test_create_session(client):
    resp = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["session_id"]) == 36  # uuid
    # 幂等性不要求，但重复调用应产生不同 session
    resp2 = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp2.json()["session_id"] != body["session_id"]


async def test_create_session_source_real_traffic(client):
    """S10 Task1：popup 用户开录即真实流量，POST 带 source 并回读。"""
    sid = (await client.post("/api/v1/sessions",
                             json={"target_system": "njmind",
                                   "note": "real", "source": "real_traffic"})).json()["session_id"]
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import RecordingSession
    db = SessionLocal()
    try:
        row = db.execute(select(RecordingSession).where(RecordingSession.id == sid)).scalar_one()
        assert row.source == "real_traffic"
    finally:
        db.close()


async def test_create_session_source_invalid_422(client):
    resp = await client.post("/api/v1/sessions", json={"source": "production"})
    assert resp.status_code == 422


async def test_create_session_source_defaults_demo(client):
    """旧客户端/auto_record 不传 source：缺省 demo（C2 输入可区分）。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import RecordingSession
    db = SessionLocal()
    try:
        row = db.execute(select(RecordingSession).where(RecordingSession.id == sid)).scalar_one()
        assert row.source == "demo"
    finally:
        db.close()
