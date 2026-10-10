import os
import tempfile

# 每进程独立测试库（lessons #46/#58 机制化根治）：共享 ./test.db 是
# 并发互撞（两进程互相 drop/create）与残留自伤的总根源。pid 后缀让
# 任意两个 pytest 进程天然隔离；退出时清理（残留不再影响下次）。
# 显式设 KEEP_TEST_DB=1 可保留供排查。
_TEST_DB = os.path.join(tempfile.gettempdir(), f"sl-test-{os.getpid()}.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
# 预置空 LLM_API_KEY：load_dotenv 默认不覆盖已存在键，确保测试进程永不加载真实 key（Fake/MockTransport 铁律）
os.environ["LLM_API_KEY"] = ""
# S22 块 T：回放截图（视觉基线）写测试临时目录，不污染真实 artifacts/
_TEST_ARTIFACT_DIR = tempfile.mkdtemp(prefix="sl-test-artifacts-")
os.environ["REPLAY_ARTIFACT_DIR"] = _TEST_ARTIFACT_DIR

import atexit


def _cleanup_test_db() -> None:
    if os.environ.get("KEEP_TEST_DB") == "1":
        return
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(_TEST_DB + suffix)
        except OSError:
            pass


atexit.register(_cleanup_test_db)

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
        # events 采集通道豁免鉴权但要求插件共享头（评审 #4 跨域污染守卫）
        c.headers["X-SkillLens-Agent"] = "1"
        yield c
    Base.metadata.drop_all(engine)
