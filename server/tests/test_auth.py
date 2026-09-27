"""S21 块 S：用户/会话/认证（TDD 先红）。

覆盖：密码哈希往返、错误密码拒绝、用户名重复、token 签发/解析/过期/登出失效。
API 层（登录端点、require_user 401/403）见 test_auth_api.py。
"""
from datetime import timedelta

import pytest

from app import auth
from app.auth import (
    create_user,
    hash_password,
    issue_token,
    resolve_token,
    verify_password,
)
from app.db import SessionLocal
from app.models import AuthToken, Base, User


@pytest.fixture(autouse=True)
def _db():
    from app.db import engine
    Base.metadata.create_all(engine)
    yield
    db = SessionLocal()
    db.query(AuthToken).delete()
    db.query(User).delete()
    db.commit()
    db.close()


def test_password_hash_roundtrip():
    h = hash_password("secret-123")
    assert h.startswith("pbkdf2$")
    assert "secret-123" not in h
    assert verify_password("secret-123", h)
    assert not verify_password("wrong", h)


def test_create_user_duplicate_rejected():
    db = SessionLocal()
    create_user(db, "alice", "pw-1", "reviewer")
    with pytest.raises(ValueError):
        create_user(db, "alice", "pw-2", "viewer")
    db.close()


def test_token_issue_and_resolve():
    db = SessionLocal()
    user = create_user(db, "bob", "pw", "viewer")
    token = issue_token(db, user.id)
    resolved = resolve_token(db, token)
    assert resolved is not None
    assert resolved.username == "bob"
    db.close()


def test_token_unknown_rejected():
    db = SessionLocal()
    assert resolve_token(db, "no-such-token") is None
    db.close()


def test_token_expired_rejected():
    db = SessionLocal()
    user = create_user(db, "carol", "pw", "admin")
    token = issue_token(db, user.id, expires=timedelta(seconds=-1))
    assert resolve_token(db, token) is None
    db.close()


def test_logout_invalidates_token():
    db = SessionLocal()
    user = create_user(db, "dave", "pw", "reviewer")
    token = issue_token(db, user.id)
    assert resolve_token(db, token) is not None
    auth.logout(db, token)
    assert resolve_token(db, token) is None
    db.close()


def test_token_stored_hashed_not_plaintext():
    db = SessionLocal()
    user = create_user(db, "erin", "pw", "viewer")
    token = issue_token(db, user.id)
    rows = db.query(AuthToken).filter_by(user_id=user.id).all()
    assert all(r.token_hash != token for r in rows)
    db.close()
