"""S42 安全红线：异常文本落库统一脱敏。

llm_call_log 侧的 URL 脱敏纪律（gateway）延伸到所有 error_text/attribution
落库点——Playwright/httpx 异常常内嵌目标系统/网关 URL，原样落库即泄漏。
"""
import re

# 带 scheme 的 URL（主形态）
_URL_RE = re.compile(r"https?://\S+")
# 裸 host:port/path 形态（Connection reset 类消息常见——内网地址无
# scheme 直书，评审实证盲区）：IP[:port] 或 内网段域名开头
_BARE_HOST_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/\S*)?"
    r"|\b(?:[a-z0-9-]+\.)+(?:local|internal|lan|intranet)\b\S*", re.IGNORECASE)


def sanitize_error(exc: BaseException | str) -> str:
    """异常 → "类型: 摘要"，URL（含裸 IP:port 形态）统一替换为 <url>，截断 500 字符。"""
    text = str(exc)
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {text}"
    text = _URL_RE.sub("<url>", text)
    text = _BARE_HOST_RE.sub("<url>", text)
    return text[:500]
