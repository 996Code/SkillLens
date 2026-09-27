"""S21 块 S T2：认证 API + 依赖。

- POST /auth/login {username,password} → {token,user}（错口令 401）；
- POST /auth/logout（Bearer 头里的 token 立即失效）；
- GET /auth/me → 当前用户；
- POST /auth/users（仅 admin）→ 建号（重名 409）；
- require_user / require_role：main.py 对除 health/events/auth 外全部 router 挂
  require_user；插件上报通道（/sessions、/sessions/{id}/events）豁免。
"""
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import create_user, issue_token, logout, resolve_token, verify_password
from app.db import SessionLocal
from app.models import User

router = APIRouter()

ROLES = Literal["admin", "reviewer", "viewer"]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_user(authorization: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    user = resolve_token(db, authorization[len("Bearer "):])
    if user is None:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return user


def require_role(*roles: str):
    def dep(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"requires role: {roles}")
        return user
    return dep


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str
    password: str
    role: ROLES = "viewer"


def _user_out(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/login")
async def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="wrong username or password")
    token = issue_token(db, user.id)
    return {"token": token, "user": _user_out(user)}


@router.post("/auth/logout")
async def logout_ep(authorization: str | None = Header(default=None),
                    db: Session = Depends(get_db)):
    if authorization and authorization.startswith("Bearer "):
        logout(db, authorization[len("Bearer "):])
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(require_user)):
    return _user_out(user)


@router.post("/auth/users", status_code=201)
async def create_user_ep(body: UserIn, db: Session = Depends(get_db),
                        admin: User = Depends(require_role("admin"))):
    try:
        user = create_user(db, body.username, body.password, body.role)
    except ValueError:
        raise HTTPException(status_code=409, detail="username already exists")
    return _user_out(user)
