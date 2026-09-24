async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


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
