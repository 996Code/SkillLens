"""S42 安全红线：error_text 落库统一 URL 脱敏。

llm_call_log 侧的脱敏纪律（gateway）延伸到 replay/agents 的 error run——
Playwright/httpx 异常常内嵌目标系统/网关 URL，原样落库即泄漏。
"""
from app.sanitize import sanitize_error


def test_masks_http_urls():
    exc = RuntimeError("connect ECONNREFUSED http://192.168.99.22:8080/api/login failed")
    out = sanitize_error(exc)
    assert "192.168.99.22" not in out
    assert "http" not in out
    assert "ECONNREFUSED" in out


def test_masks_https_urls():
    out = sanitize_error("gateway 401 at https://llm.internal/v1/chat/completions")
    assert "llm.internal" not in out
    assert "401" in out


def test_keeps_plain_messages():
    assert sanitize_error(ValueError("net reset")) == "ValueError: net reset"


def test_truncates_long_messages():
    out = sanitize_error(RuntimeError("x" * 900))
    assert len(out) <= 500
