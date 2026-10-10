"""S42 安全红线：error_text 落库统一 URL 脱敏。

llm_call_log 侧的脱敏纪律（gateway）延伸到 replay/agents 的 error run——
Playwright/httpx 异常常内嵌目标系统/网关 URL，原样落库即泄漏。
"""
from app.sanitize import sanitize_error


def test_masks_http_urls():
    exc = RuntimeError("connect ECONNREFUSED http://192.0.2.99:8080/api/login failed")
    out = sanitize_error(exc)
    assert "192.0.2.99" not in out
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


def test_bare_ip_port_sanitized():
    """评审盲区：裸 IP:port 形态（无 scheme——Connection reset 类消息）
    同样必须脱敏。"""
    from app.sanitize import sanitize_error
    out = sanitize_error(RuntimeError("net reset 192.168.1.50:8080/mb3/login failed"))
    assert "192.168.1.50" not in out and "<url>" in out
    # 纯 IP 无 port
    out2 = sanitize_error("connect 10.0.0.8 refused")
    assert "10.0.0.8" not in out2 and "<url>" in out2
