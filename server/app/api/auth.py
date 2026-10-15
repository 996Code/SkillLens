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
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (create_user, hash_password, issue_token, logout,
                      resolve_token, verify_password)
from app.db import SessionLocal
from app.models import AuthToken, User

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
    dep.roles = roles
    return dep


# viewer=只读契约的唯一来源：所有变更端点（写库/写盘/触发浏览器执行/烧 LLM
# 配额）挂这一份依赖，逐端点声明 dependencies=WRITE_GUARD
WRITE_GUARD = [Depends(require_role("admin", "reviewer"))]


class LoginIn(BaseModel):
    username: str
    password: str


# 用户名枚举侧信道：未知用户若直接 401，就省掉一次 100k 轮 pbkdf2（数十毫秒），
# 与"已知用户+错口令"的响应时差足以枚举有效账号。未知用户也对 dummy hash 走
# 一次等强度校验（结果丢弃）——启动期算一次，登录路径恒定开销。
_DUMMY_HASH = hash_password("skilllens-timing-equalizer")


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: ROLES = "viewer"


def _user_out(user: User) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/login")
async def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok:
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


@router.post("/auth/plugin-session")
async def plugin_session(x_skilllens_agent: str | None = Header(default=None),
                          db: Session = Depends(get_db)) -> dict:
    """内部部署免登录：PLUGIN_TRUST=1 时插件凭共享头换 admin token
    （无凭据传输——内部使用不设登录门槛；默认关，公网部署零暴露）。"""
    import os
    if os.environ.get("PLUGIN_TRUST") != "1" or x_skilllens_agent != "1":
        raise HTTPException(status_code=403, detail="plugin trust disabled")
    user = db.query(User).filter_by(role="admin").order_by(User.id).first()
    if user is None:
        raise HTTPException(status_code=500, detail="no admin user")
    token = issue_token(db, user.id)
    return {"token": token, "user": _user_out(user)}


@router.post("/auth/users", status_code=201)
async def create_user_ep(body: UserIn, db: Session = Depends(get_db),
                        admin: User = Depends(require_role("admin"))):
    try:
        user = create_user(db, body.username, body.password, body.role)
    except ValueError:
        raise HTTPException(status_code=409, detail="username already exists")
    return _user_out(user)


@router.get("/auth/users")
async def list_users(db: Session = Depends(get_db),
                     admin: User = Depends(require_role("admin"))):
    """多账号基础：admin 可列全部账号（密码哈希不外泄）。"""
    return [_user_out(u) for u in db.query(User).order_by(User.id).all()]


class UserUpdateIn(BaseModel):
    role: ROLES | None = None
    password: str | None = None


@router.patch("/auth/users/{user_id}")
async def update_user(user_id: int, body: UserUpdateIn,
                      db: Session = Depends(get_db),
                      admin: User = Depends(require_role("admin"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="user not found")
    if body.password is not None:
        if len(body.password) < 8:
            raise HTTPException(422, detail="password too short (min 8)")
        user.password_hash = hash_password(body.password)
        # 密码重置后吊销该用户全部既有 token（旧会话失效）
        db.query(AuthToken).filter(AuthToken.user_id == user_id).delete()
    if body.role is not None:
        # 最后一个 admin 不得降级（锁死自己锁死系统）
        if (user.role == "admin" and body.role != "admin"
                and db.query(User).filter(User.role == "admin").count() <= 1):
            raise HTTPException(409, detail="cannot demote the last admin")
        user.role = body.role
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.delete("/auth/users/{user_id}")
async def delete_user_ep(user_id: int, db: Session = Depends(get_db),
                         admin: User = Depends(require_role("admin"))):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, detail="user not found")
    if user.id == admin.id:
        raise HTTPException(409, detail="cannot delete yourself")
    if (user.role == "admin"
            and db.query(User).filter(User.role == "admin").count() <= 1):
        raise HTTPException(409, detail="cannot delete the last admin")
    db.query(AuthToken).filter(AuthToken.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"ok": True}
