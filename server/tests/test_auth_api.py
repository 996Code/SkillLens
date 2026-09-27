"""S21 块 S T2：认证 API + require_user 依赖（TDD 先红）。

- bare_client：无认证头（测 401/插件豁免通道）；
- client（conftest）：admin + 默认 Bearer 头（存量测试零改动）。
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.auth import create_user, issue_token
from app.db import SessionLocal
from app.main import app


@pytest.fixture
async def bare_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_login_ok_and_wrong_password(bare_client, client):
    db = SessionLocal()
    create_user(db, "alice", "pw-123", "reviewer")
    db.close()
    resp = await bare_client.post("/api/v1/auth/login",
                                  json={"username": "alice", "password": "pw-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"] and body["user"]["username"] == "alice"
    assert body["user"]["role"] == "reviewer"
    resp = await bare_client.post("/api/v1/auth/login",
                                 json={"username": "alice", "password": "bad"})
    assert resp.status_code == 401


async def test_me_requires_token(bare_client):
    resp = await bare_client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_with_token(bare_client, client):
    resp = await bare_client.get("/api/v1/auth/me",
                                 headers={"Authorization": client.headers["Authorization"]})
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_logout_invalidates(bare_client, client):
    headers = {"Authorization": client.headers["Authorization"]}
    resp = await bare_client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200
    resp = await bare_client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


async def test_protected_api_requires_token(bare_client):
    resp = await bare_client.get("/api/v1/skills")
    assert resp.status_code == 401


async def test_extension_channel_exempt(bare_client, client):
    # 插件豁免通道：health 与会话上报不需要认证（client 夹具负责建表）
    resp = await bare_client.get("/api/v1/health")
    assert resp.status_code == 200
    resp = await bare_client.post("/api/v1/sessions", json={"page_url": "https://x.example/"})
    assert resp.status_code == 200


async def test_admin_creates_user(bare_client, client):
    resp = await bare_client.post("/api/v1/auth/users",
                                  headers={"Authorization": client.headers["Authorization"]},
                                  json={"username": "bob", "password": "pw-2", "role": "viewer"})
    assert resp.status_code == 201
    assert resp.json()["role"] == "viewer"


async def test_non_admin_cannot_create_user(bare_client, client):
    db = SessionLocal()
    create_user(db, "carol", "pw-3", "reviewer")
    token = issue_token(db, _uid(db, "carol"))
    db.close()
    resp = await bare_client.post(
        "/api/v1/auth/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "dave", "password": "pw", "role": "viewer"})
    assert resp.status_code == 403


async def test_duplicate_user_409(bare_client, client):
    resp = await bare_client.post("/api/v1/auth/users",
                                  headers={"Authorization": client.headers["Authorization"]},
                                  json={"username": "s21-admin", "password": "x", "role": "viewer"})
    assert resp.status_code == 409


def _uid(db, username):
    from app.models import User
    return db.query(User).filter_by(username=username).first().id
