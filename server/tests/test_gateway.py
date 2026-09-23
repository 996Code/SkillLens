import json
import os

import httpx
from sqlalchemy import select

from app.db import SessionLocal
from app.llm.gateway import complete, get_provider
from app.models import LlmCallLog


def test_dotenv_preserves_existing_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./preserved.db")
    import importlib

    import app.config as config

    importlib.reload(config)
    assert config.DATABASE_URL == "sqlite:///./preserved.db"


def test_fake_provider_fallback(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    scripted = json.dumps({"name": "FakeSkill", "description": "fake"})
    monkeypatch.setenv("LLM_FAKE_RESPONSE", scripted)
    provider = get_provider()
    assert provider.name == "fake"
    result = provider.complete("hello")
    assert result.text == scripted
    assert result.model == "fake-model"


def test_openai_compat_provider_request(monkeypatch):
    from app.llm.provider import OpenAICompatProvider

    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        })

    transport = httpx.MockTransport(handler)
    provider = OpenAICompatProvider("http://llm.test/v1", "sk-x", "m1", 512, transport=transport)
    result = provider.complete("hi")
    assert result.text == "ok"
    assert result.prompt_tokens == 11
    assert captured["url"] == "http://llm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-x"
    assert captured["body"]["model"] == "m1"
    assert captured["body"]["max_tokens"] == 512
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


def test_complete_logs_to_db(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "logged-response")
    from app.db import engine
    from app.models import Base

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        result = complete(db, "skill_naming", "prompt-abc")
        assert result.text == "logged-response"
        row = db.execute(select(LlmCallLog).order_by(LlmCallLog.id.desc())).scalars().first()
        assert row.purpose == "skill_naming"
        assert row.prompt == "prompt-abc"
        assert row.response == "logged-response"
        assert row.provider == "fake"
        assert row.latency_ms >= 0
    finally:
        db.close()
