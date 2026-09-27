"""S21 块 S：用户/密码/会话纯函数层（无 FastAPI 依赖，便于单测）。

- 密码：stdlib pbkdf2_hmac（不引入新依赖），格式 pbkdf2$<iter>$<salt_hex>$<hash_hex>；
- token：secrets.token_urlsafe(32) 签发，SHA-256 哈希落库（明文不落库）；
- 过期判定用 UTC（expires_at 存 naive UTC，与 utcnow() 一致）。
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import AuthToken, User

_PBKDF2_ITER = 100_000
DEFAULT_TOKEN_TTL = timedelta(days=7)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITER)
    return f"pbkdf2${_PBKDF2_ITER}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iter_s, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iter_s))
    return secrets.compare_digest(digest.hex(), hash_hex)


def create_user(db: Session, username: str, password: str, role: str = "viewer") -> User:
    if db.query(User).filter_by(username=username).first():
        raise ValueError(f"username already exists: {username}")
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    return user


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user_id: int, expires: timedelta = DEFAULT_TOKEN_TTL) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthToken(user_id=user_id, token_hash=_hash_token(token),
                     expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + expires))
    db.commit()
    return token


def resolve_token(db: Session, token: str) -> User | None:
    row = db.query(AuthToken).filter_by(token_hash=_hash_token(token)).first()
    if row is None:
        return None
    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return db.get(User, row.user_id)


def logout(db: Session, token: str) -> None:
    row = db.query(AuthToken).filter_by(token_hash=_hash_token(token)).first()
    if row is not None:
        db.delete(row)
        db.commit()
