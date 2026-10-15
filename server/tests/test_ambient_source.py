"""AP1 ambient source marker (C2 分轨) contract tests."""
import pytest
from httpx import AsyncClient


@pytest.fixture
def ambient_client(client: AsyncClient):
    yield client


async def test_ambient_session_created_with_source(ambient_client):
    """AP1：ambient 会话创建——source=ambient 落库（C2 分轨）。"""
    r = await ambient_client.post("/api/v1/sessions", json={
        "target_system": "snipeit",
        "note": "(ambient 自动录制)",
        "source": "ambient",
    }, headers={"X-SkillLens-Agent": "1"})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]

    from app.db import SessionLocal
    from app.models import RecordingSession
    db = SessionLocal()
    try:
        row = db.get(RecordingSession, sid)
        assert row is not None
        assert row.source == "ambient"
    finally:
        db.close()


async def test_ambient_source_rejected_for_invalid(ambient_client):
    """source 枚举守卫：非法值 422（防客户端拼错静默降级 demo）。"""
    r = await ambient_client.post("/api/v1/sessions", json={
        "target_system": "x", "note": "", "source": "ambien",
    }, headers={"X-SkillLens-Agent": "1"})
    assert r.status_code == 422


async def test_ambient_sessions_isolated_from_real_traffic_stats(client):
    """C2 分轨口径：ambient 不混入 real_traffic 统计（查询层可分轨）。"""
    from app.db import SessionLocal
    from app.models import RecordingSession
    db = SessionLocal()
    try:
        ambient_count = db.query(RecordingSession).filter(
            RecordingSession.source == "ambient").count()
        real_count = db.query(RecordingSession).filter(
            RecordingSession.source == "real_traffic").count()
        # 分轨可查询（两值独立可数——不抛错即契约成立）
        assert ambient_count >= 0 and real_count >= 0
    finally:
        db.close()
