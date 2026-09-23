import time

from sqlalchemy.orm import Session

from app import config
from app.llm.provider import FakeProvider, OpenAICompatProvider, Provider
from app.models import LlmCallLog


def get_provider() -> Provider:
    if config.LLM_API_KEY:
        return OpenAICompatProvider(config.LLM_BASE_URL, config.LLM_API_KEY,
                                    config.LLM_MODEL, config.LLM_MAX_TOKENS)
    from app.llm.provider import default_fake_script
    return FakeProvider(default_fake_script())


def complete(db: Session, purpose: str, prompt: str):
    provider = get_provider()
    started = time.perf_counter()
    result = provider.complete(prompt)
    latency_ms = int((time.perf_counter() - started) * 1000)
    db.add(LlmCallLog(purpose=purpose, provider=result.provider, model=result.model,
                      prompt=prompt, response=result.text,
                      prompt_tokens=result.prompt_tokens,
                      completion_tokens=result.completion_tokens,
                      latency_ms=latency_ms))
    db.commit()
    return result
