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

# S22 块 T 视觉回归阈值（私有化可调）：dHash 汉明距离初筛线 /
# 逐像素通道容差 / 差异像素占比阈值（0.02 = 2%）。
VISUAL_HASH_MAX_DISTANCE = int(os.environ.get("VISUAL_HASH_MAX_DISTANCE", "4"))
VISUAL_PIXEL_TOLERANCE = int(os.environ.get("VISUAL_PIXEL_TOLERANCE", "16"))
VISUAL_DIFF_THRESHOLD = float(os.environ.get("VISUAL_DIFF_THRESHOLD", "0.02"))

# S23 块 V 性能漂移阈值：current > 中位数 × ratio 判漂移（严格大于）；历史 <3 次不判定
PERF_DRIFT_RATIO = float(os.environ.get("PERF_DRIFT_RATIO", "1.5"))

# S24 块 U：flaky 重跑开关（1=execute fail 自动重试一次）；定位提案自动晋升所需通过次数
REPLAY_FLAKY_RERUN = os.environ.get("REPLAY_FLAKY_RERUN", "1") == "1"
LOCATE_AUTO_PROMOTE_N = int(os.environ.get("LOCATE_AUTO_PROMOTE_N", "3"))
