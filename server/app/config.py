import os

from dotenv import load_dotenv

load_dotenv()  # 读 server/.env（不入库），已存在的进程环境变量优先

HOST = "127.0.0.1"
PORT = 8710
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./skilllens.db")
API_PREFIX = "/api/v1"

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "fake-model")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
