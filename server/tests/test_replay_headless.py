from app.replay.runner import _cdp_url, _channel, _headless


def test_headless_default(monkeypatch):
    monkeypatch.delenv("REPLAY_HEADLESS", raising=False)
    assert _headless() is True


def test_headless_env_off(monkeypatch):
    monkeypatch.setenv("REPLAY_HEADLESS", "0")
    assert _headless() is False


def test_headless_env_on_and_garbage(monkeypatch):
    monkeypatch.setenv("REPLAY_HEADLESS", "1")
    assert _headless() is True
    monkeypatch.setenv("REPLAY_HEADLESS", "yes")
    assert _headless() is True


def test_channel_default_chromium(monkeypatch):
    monkeypatch.delenv("REPLAY_CHANNEL", raising=False)
    assert _channel() == "chromium"


def test_channel_chrome(monkeypatch):
    monkeypatch.setenv("REPLAY_CHANNEL", "chrome")
    assert _channel() == "chrome"


def test_channel_empty_is_chromium(monkeypatch):
    monkeypatch.setenv("REPLAY_CHANNEL", "")
    assert _channel() == "chromium"


def test_cdp_url_default_empty(monkeypatch):
    monkeypatch.delenv("REPLAY_CDP_URL", raising=False)
    assert _cdp_url() == ""


def test_cdp_url_env(monkeypatch):
    monkeypatch.setenv("REPLAY_CDP_URL", "http://127.0.0.1:9222")
    assert _cdp_url() == "http://127.0.0.1:9222"
