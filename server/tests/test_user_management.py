"""User management API contract tests (admin-only, multi-account basis)."""
import pytest
from httpx import AsyncClient

from app.auth import create_user, hash_password, issue_token
from app.db import SessionLocal
from app.models import AuthToken, User, utcnow
from datetime import timedelta
import hashlib
import secrets


async def _viewer_token(db: SessionLocal) -> str:
    user = create_user(db, "um-viewer", "pw-um", "viewer")
    return issue_token(db, user.id)


async def _mk_admin_token(client: AsyncClient) -> str:
    # conftest client 自带 admin token——直接复用（登录态即 admin）
    return None  # 用 client 默认头


async def test_list_users_admin_only(client: AsyncClient):
    r = await client.get("/api/v1/auth/users")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert any(u["username"] == "s21-admin" for u in rows)
    assert all("password_hash" not in u for u in rows), "密码哈希不得外泄"
    assert all(u.get("role") in ("admin", "reviewer", "viewer") for u in rows)


async def test_list_users_viewer_forbidden(client: AsyncClient):
    db = SessionLocal()
    try:
        tok = await _viewer_token(db)
    finally:
        db.close()
    r = await client.get("/api/v1/auth/users",
                         headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


async def test_create_user_role_validation(client: AsyncClient):
    r = await client.post("/api/v1/auth/users", json={
        "username": "bad-role", "password": "pw-123456", "role": "superuser"})
    assert r.status_code == 422
    r2 = await client.post("/api/v1/auth/users", json={
        "username": "", "password": "pw-123456", "role": "viewer"})
    assert r2.status_code == 422


async def test_update_user_role_and_password(client: AsyncClient):
    # 建一个用户
    created = (await client.post("/api/v1/auth/users", json={
        "username": "um-target", "password": "pw-old-123", "role": "viewer"})).json()
    uid = created["id"]

    # 改角色
    r = await client.patch(f"/api/v1/auth/users/{uid}",
                           json={"role": "reviewer"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "reviewer"

    # 重置密码（新密码可登录）
    r2 = await client.patch(f"/api/v1/auth/users/{uid}",
                            json={"password": "pw-new-456"})
    assert r2.status_code == 200
    login = await client.post("/api/v1/auth/login", json={
        "username": "um-target", "password": "pw-new-456"})
    assert login.status_code == 200, "重置后新密码可登录"
    # 旧密码失效
    old = await client.post("/api/v1/auth/login", json={
        "username": "um-target", "password": "pw-old-123"})
    assert old.status_code == 401


async def test_delete_user_guards(client: AsyncClient):
    created = (await client.post("/api/v1/auth/users", json={
        "username": "um-del", "password": "pw-del-123", "role": "viewer"})).json()
    uid = created["id"]
    # 删除成功
    r = await client.delete(f"/api/v1/auth/users/{uid}")
    assert r.status_code == 200
    # 重复删除 404
    r2 = await client.delete(f"/api/v1/auth/users/{uid}")
    assert r2.status_code == 404
    # 不能删自己（admin 自身）
    me = (await client.get("/api/v1/auth/me")).json()
    r3 = await client.delete(f"/api/v1/auth/users/{me['id']}")
    assert r3.status_code == 409, "不能删除自己"
