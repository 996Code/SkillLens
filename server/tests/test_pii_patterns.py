"""J4 PII 脱敏规则配置化（Sprint 20 块J Task 1）。

PII_PATTERNS env（逗号分隔正则片段）追加到 page_snapshot 敏感词表，
供私有化部署自定义业务敏感字段（如 idcard/phone）。默认空 → 行为不变。
config 在 import 时读 env，故用 monkeypatch.setenv + importlib.reload(config)
+ page_snapshot._rebuild_sensitive_re() 刷新；用例结束必须还原默认词表。
"""
import importlib

from app.replay import page_snapshot
from app.replay.page_snapshot import REDACTED, redact_value


def _rebuild(monkeypatch, patterns: str | None) -> None:
    """按给定 env 值刷新 config 与敏感正则（None 表示清除 env，回到默认）。"""
    if patterns is None:
        monkeypatch.delenv("PII_PATTERNS", raising=False)
    else:
        monkeypatch.setenv("PII_PATTERNS", patterns)
    from app import config

    importlib.reload(config)
    page_snapshot._rebuild_sensitive_re()


def test_pii_patterns_redacts_custom_fields(monkeypatch):
    try:
        _rebuild(monkeypatch, "idcard,phone")
        assert redact_value("idcard", "110101199001011234") == REDACTED
        # 子串命中，与基础词表（如 access_token）同语义
        assert redact_value("user_phone", "13800138000") == REDACTED
        # 大小写不敏感（re.I）
        assert redact_value("IDCard", "x") == REDACTED
        # 基础词表仍然生效
        assert redact_value("password", "x") == REDACTED
    finally:
        _rebuild(monkeypatch, None)  # 还原默认词表，避免污染其他用例


def test_pii_patterns_default_unchanged(monkeypatch):
    try:
        _rebuild(monkeypatch, None)
        # 默认不脱敏自定义字段
        assert redact_value("idcard", "110101199001011234") == "110101199001011234"
        assert redact_value("phone", "13800138000") == "13800138000"
        # 基础词表行为不变
        assert redact_value("password", "x") == REDACTED
        assert redact_value("customer", "张三") == "张三"
    finally:
        _rebuild(monkeypatch, None)


def test_config_pii_patterns_parsing(monkeypatch):
    """逗号分隔 + 去空白 + 丢弃空片段。"""
    from app import config

    try:
        monkeypatch.setenv("PII_PATTERNS", " idcard, phone ,,mobile ")
        importlib.reload(config)
        assert config.PII_PATTERNS == ["idcard", "phone", "mobile"]
        monkeypatch.delenv("PII_PATTERNS")
        importlib.reload(config)
        assert config.PII_PATTERNS == []
    finally:
        monkeypatch.delenv("PII_PATTERNS", raising=False)
        importlib.reload(config)
        page_snapshot._rebuild_sensitive_re()
