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

ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()
]

# J4 PII 脱敏规则配置化：逗号分隔的正则片段（追加到敏感字段词表），
# 供私有化部署自定义业务敏感字段（如 idcard,phone）。默认空 = 行为不变。
PII_PATTERNS: list[str] = [
    p.strip() for p in os.environ.get("PII_PATTERNS", "").split(",") if p.strip()
]
