"""S42 安全红线：异常文本落库统一脱敏。

llm_call_log 侧的 URL 脱敏纪律（gateway）延伸到所有 error_text/attribution
落库点——Playwright/httpx 异常常内嵌目标系统/网关 URL，原样落库即泄漏。
"""
import re

_URL_RE = re.compile(r"https?://\S+")


def sanitize_error(exc: BaseException | str) -> str:
    """异常 → "类型: 摘要"，URL 统一替换为 <url>，截断 500 字符。"""
    text = str(exc)
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {text}"
    return _URL_RE.sub("<url>", text)[:500]
