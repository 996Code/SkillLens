import os

# 必须在导入 app.main 之前设置环境变量，使 app.db 的 engine 指向测试库
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
# 预置空 LLM_API_KEY：load_dotenv 默认不覆盖已存在键，确保测试进程永不加载真实 key（Fake/MockTransport 铁律）
os.environ["LLM_API_KEY"] = ""

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal, engine
from app.main import app
from app.models import Base


@pytest.fixture
async def client():
    # 先 drop 再 create：上次异常中断的运行可能在 test.db 留残行（如 user 唯一键），
    # setup 自清理保证夹具幂等。
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    # S21 块 S：API 默认要求认证——夹具内置 admin 账号+token，存量测试零改动。
    # 无认证场景用各测试文件自建的 bare_client。
    from app.auth import create_user, issue_token
    db = SessionLocal()
    try:
        user = create_user(db, "s21-admin", "test-only-password", "admin")
        token = issue_token(db, user.id)
    finally:
        db.close()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
    Base.metadata.drop_all(engine)
