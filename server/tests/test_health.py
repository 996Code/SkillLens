async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "sessions_no_navigation" in resp.json()


async def test_cors_preflight(client):
    resp = await client.options(
        "/api/v1/sessions",
        headers={"Origin": "http://njmind.example", "Access-Control-Request-Method": "POST"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"


async def test_cors_default_allows_all(client):
    resp = await client.options(
        "/api/v1/sessions",
        headers={"Origin": "http://example.com", "Access-Control-Request-Method": "POST"},
    )
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_cors_env_parsed(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.local, http://b.local")
    import importlib

    import app.config as cfg

    importlib.reload(cfg)
    assert cfg.ALLOWED_ORIGINS == ["http://a.local", "http://b.local"]
    monkeypatch.delenv("ALLOWED_ORIGINS")
    importlib.reload(cfg)
    assert cfg.ALLOWED_ORIGINS == ["*"]


async def test_health_reports_no_navigation_ratio(client):
    """防再生④：会话落库后 navigation=0 的比率进健康端点——零 navigation
    会话失系统派生锚（105 会话实证），比率可见才能发现采集退化。"""
    from app.db import SessionLocal
    from app.models import RecordingSession, RawEvent
    db = SessionLocal()
    try:
        import uuid
        s1 = RecordingSession(id=str(uuid.uuid4()), note="t-nav")
        s2 = RecordingSession(id=str(uuid.uuid4()), note="t-nonav")
        db.add_all([s1, s2]); db.flush()
        db.add(RawEvent(session_id=s1.id, page_id="p1", seq=0, ts=0,
                        kind="navigation",
                        payload={"type": "page-load", "url": "http://h/"}))
        db.add(RawEvent(session_id=s2.id, page_id="p1", seq=0, ts=0,
                        kind="action",
                        payload={"type": "click", "target": {"label": "x"}}))
        db.commit()
        r = await client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert "sessions_no_navigation" in body
        # 至少能感知到无 navigation 会话存在（比率>0）
        assert body["sessions_no_navigation"]["ratio"] > 0
    finally:
        db.query(RawEvent).delete()
        db.query(RecordingSession).delete()
        db.commit(); db.close()
