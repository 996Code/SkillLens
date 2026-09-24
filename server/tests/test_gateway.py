import json
import os

import httpx
import pytest
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


def test_complete_logs_on_provider_error(monkeypatch):
    class ExplodingProvider:
        name = "openai-compat"

        def complete(self, prompt):
            raise RuntimeError("boom-connection")

    import app.llm.gateway as llm_gateway
    monkeypatch.setattr(llm_gateway, "get_provider", lambda: ExplodingProvider())

    from app.db import engine
    from app.models import Base

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        with pytest.raises(RuntimeError):
            llm_gateway.complete(db, "skill_naming", "prompt-xyz")
        row = db.execute(select(LlmCallLog).order_by(LlmCallLog.id.desc())).scalars().first()
        assert row.purpose == "skill_naming"
        assert row.provider == "openai-compat"
        assert row.prompt == "prompt-xyz"
        assert "RuntimeError" in row.response and "boom" in row.response
        assert row.prompt_tokens is None
        assert row.completion_tokens is None
        assert row.latency_ms >= 0
    finally:
        db.close()


def test_complete_error_summary_masks_gateway_url(monkeypatch):
    """红线：异常摘要不得把网关 URL 落进 llm_call_log（httpx str(e) 内嵌 URL）。"""
    import app.llm.gateway as gw
    from app.db import engine
    from app.models import Base
    Base.metadata.create_all(engine)
    class FakeExplode:
        name = "openai-compat"
        model = "m"
        def complete(self, prompt):
            import httpx
            req = httpx.Request("POST", "http://secret-gateway.local:18080/v1/chat/completions")
            resp = httpx.Response(401, request=req)
            raise httpx.HTTPStatusError("bad", request=req, response=resp)
    monkeypatch.setattr(gw, "get_provider", lambda: FakeExplode())
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        import pytest as _p
        with _p.raises(Exception):
            gw.complete(db, "skill_naming", "p")
        from sqlalchemy import select
        row = db.execute(select(gw.LlmCallLog).order_by(gw.LlmCallLog.id.desc())).scalars().first()
        assert "secret-gateway.local" not in row.response
        assert "HTTPStatusError" in row.response
    finally:
        db.close()
