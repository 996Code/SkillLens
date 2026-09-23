import os

# 必须在导入 app.main 之前设置环境变量，使 app.db 的 engine 指向测试库
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import engine
from app.main import app
from app.models import Base


@pytest.fixture
async def client():
    Base.metadata.create_all(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    Base.metadata.drop_all(engine)
