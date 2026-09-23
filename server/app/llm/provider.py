import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass
class LlmResult:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    provider: str
    model: str


class Provider(ABC):
    name: str = "abstract"

    @abstractmethod
    def complete(self, prompt: str) -> LlmResult: ...


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, scripted: str):
        self.scripted = scripted
        self.model = "fake-model"

    def complete(self, prompt: str) -> LlmResult:
        return LlmResult(self.scripted, 1, 1, "fake", self.model)


class OpenAICompatProvider(Provider):
    name = "openai-compat"

    def __init__(self, base_url: str, api_key: str, model: str, max_tokens: int,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.transport = transport

    def complete(self, prompt: str) -> LlmResult:
        with httpx.Client(transport=self.transport) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "max_tokens": self.max_tokens,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=60,
            )
        resp.raise_for_status()
        data = resp.json()
        usage = data.get("usage") or {}
        return LlmResult(
            text=data["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            provider=self.name,
            model=self.model,
        )


def default_fake_script() -> str:
    return os.environ.get("LLM_FAKE_RESPONSE") or json.dumps(
        {"name": "FakeSkill", "description": "fake"})
