import time

from sqlalchemy.orm import Session

from app import config
from app.llm.provider import FakeProvider, OpenAICompatProvider, Provider
from app.models import LlmCallLog
from app.sanitize import sanitize_error


def get_provider() -> Provider:
    if config.LLM_API_KEY:
        return OpenAICompatProvider(config.LLM_BASE_URL, config.LLM_API_KEY,
                                    config.LLM_MODEL, config.LLM_MAX_TOKENS)
    from app.llm.provider import default_fake_script
    return FakeProvider(default_fake_script())


def _log_failure(db: Session, purpose: str, prompt: str, provider: Provider,
                 started: float, exc: Exception):
    # C3 失败路径：provider 异常（如网关 401）也要落 llm_call_log 后 re-raise。
    # 安全红线：只记异常类型+摘要，URL 统一脱敏（sanitize_error）。
    summary = sanitize_error(exc)[:200]
    latency_ms = int((time.perf_counter() - started) * 1000)
    db.add(LlmCallLog(purpose=purpose, provider=provider.name,
                      model=getattr(provider, "model", "unknown"),
                      prompt=prompt,
                      response=summary,
                      prompt_tokens=None, completion_tokens=None,
                      latency_ms=latency_ms))
    db.commit()


def _log_success(db: Session, purpose: str, prompt: str, result, latency_ms: int):
    db.add(LlmCallLog(purpose=purpose, provider=result.provider, model=result.model,
                      prompt=prompt, response=result.text,
                      prompt_tokens=result.prompt_tokens,
                      completion_tokens=result.completion_tokens,
                      latency_ms=latency_ms))
    db.commit()


def complete(db: Session, purpose: str, prompt: str):
    provider = get_provider()
    started = time.perf_counter()
    try:
        result = provider.complete(prompt)
    except Exception as e:
        _log_failure(db, purpose, prompt, provider, started, e)
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)
    _log_success(db, purpose, prompt, result, latency_ms)
    return result


async def acomplete(db: Session, purpose: str, prompt: str):
    """S42：异步路径统一入口——同步 httpx.Client 会阻塞事件循环最长 60s
    （批回放期间 UI/插件上报全部冻结），async 端点必须走这里。"""
    provider = get_provider()
    started = time.perf_counter()
    try:
        result = await provider.acomplete(prompt)
    except Exception as e:
        _log_failure(db, purpose, prompt, provider, started, e)
        raise
    latency_ms = int((time.perf_counter() - started) * 1000)
    _log_success(db, purpose, prompt, result, latency_ms)
    return result
