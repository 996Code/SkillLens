# Sprint 3 实施计划：LLM Gateway + Skill 归纳 + 字段级 Before/After + Outcome 断言

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首次引入 LLM（OpenAI 兼容协议）：Gateway 全量 call_log 落库；对 alignment 产物做 Skill 归纳（LLM 只命名，确定性回查防幻觉）；reqBody 跨窗口确定性 diff 产出字段级 Before/After；生成 Outcome 层 2/3 断言并可在原始 Episode 上回放验证；Skill 卡片端点支撑演示 2。

**Architecture:** LLM Gateway 为 Provider 抽象 + FakeProvider（无 key 时自动回退，测试零网络）+ OpenAICompatProvider（httpx 直调 /chat/completions，无 SDK 依赖）；Skill 归纳流水线 = 构造 prompt → LLM 产出严格 JSON → 确定性回查（引用的 API 模板必须存在于骨架签名，失败降级 candidate）；字段 diff 与断言生成全程无 LLM。

**Tech Stack:** 既有栈 + httpx（已在 dev 依赖，移为运行依赖）+ python-dotenv。基线：pytest 43、vitest 19。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md`（§4.3 层 2 字段级 Before/After 裁定、§4.4 LLM Gateway、§7 Sprint 3 行）

## Global Constraints（每个任务默认遵守）

- 环境变量名固定：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_MAX_TOKENS`；**真实密钥只存 `server/.env`（.gitignore 已覆盖），任何文档/代码/测试不得出现真实值**；无 `LLM_API_KEY` 时 Gateway 自动用 FakeProvider（脚本响应来自 `LLM_FAKE_RESPONSE` 环境变量，默认 `{"name":"FakeSkill","description":"fake"}`）。
- 所有 LLM 调用必须经 Gateway 并写 `llm_call_log`（prompt 原文、响应原文、token、耗时）——C3。
- LLM 在本 Sprint 的职责边界：**只做命名与描述**；骨架、变量、断言、diff、置信度全部确定性生成；LLM 产物必须过确定性回查，失败降级 `candidate` 并记录原因。
- `llm_call_log`/`raw_event` append-only；skill/outcome_assertion/field_change 按 session 或 skill 幂等删旧插新。
- server 完成标准 = `cd server && uv run pytest tests/ -v` 全过；提交信息中文 `feat|test|chore|fix: 描述`。
- Skill 存储用 JSON 列（spec §4.3 的 YAML 是展示格式，入库为 dict，渲染端点输出时转 YAML 字符串可选）。
- 真实 LLM 与真实浏览器验证由用户在 T6 配合执行；实现者以 FakeProvider 单测为门槛。

## File Structure

```text
server/app/llm/__init__.py
server/app/llm/provider.py          # T1 Provider/LlmResult/FakeProvider/OpenAICompatProvider
server/app/llm/gateway.py           # T1 complete() + llm_call_log 落库 + provider 选择
server/app/config.py                # T1 dotenv 加载 + LLM 配置读取
server/app/models.py                # T1 LlmCallLog；T2 FieldChange；T3 Skill；T4 OutcomeAssertion
server/app/ingestion/fielddiff.py   # T2 flatten/diff_bodies 纯函数
server/app/ingestion/fieldchange.py # T2 服务：session 内同模板 POST reqBody 连续 diff
server/app/learning/__init__.py
server/app/learning/skill.py        # T3 build_prompt/parse_llm_skill/verify_skill/induce_skill
server/app/learning/outcome.py      # T4 断言生成 + verify_against_session 回放
server/app/api/llm_skills.py        # T2/T3/T4 端点（field-changes、skills、verify）
server/tests/test_gateway.py        # T1
server/tests/test_fielddiff.py      # T2
server/tests/test_skill.py          # T3
server/tests/test_outcome.py        # T4
server/.env.example                 # T5（占位值）
demo/sprint3/                       # T6
```

---

### Task 1: LLM Gateway（Provider 抽象 + Fake + OpenAI 兼容 + call_log 落库）

**Files:**
- Create: `server/app/llm/__init__.py`（空）、`server/app/llm/provider.py`、`server/app/llm/gateway.py`
- Modify: `server/app/config.py`（dotenv + LLM 配置）、`server/app/models.py`（追加 LlmCallLog）
- Create: `server/alembic/versions/*_llm_call_log.py`
- Test: `server/tests/test_gateway.py`

**Interfaces:**
- Produces:
  - `LlmResult`（dataclass：`text: str, prompt_tokens: int|None, completion_tokens: int|None, provider: str, model: str`）；
  - `Provider`（ABC：`name: str`、`complete(prompt: str) -> LlmResult`）、`FakeProvider(scripted: str)`、`OpenAICompatProvider(base_url, api_key, model, max_tokens, transport=None)`；
  - `get_provider() -> Provider`（有 `LLM_API_KEY` → OpenAI 兼容，否则 FakeProvider，脚本来自 `LLM_FAKE_RESPONSE`）；
  - `complete(db: Session, purpose: str, prompt: str) -> LlmResult`——调用 Provider 并把完整输入输出写入 `llm_call_log` 后返回；
  - ORM `LlmCallLog`：`id` 自增、`purpose` str(50)、`provider` str(30)、`model` str(100)、`prompt` Text、`response` Text、`prompt_tokens` int nullable、`completion_tokens` int nullable、`latency_ms` int、`created_at`。
- T3 消费 `complete`。

- [ ] **Step 1: 写失败测试**

`server/tests/test_gateway.py`：

```python
import json
import os

from sqlalchemy import select

from app.db import SessionLocal
from app.llm.gateway import complete, get_provider
from app.models import LlmCallLog


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
```

（文件顶部 `import httpx`；`test_complete_logs_to_db` 走 conftest 测试库——conftest 已把 `DATABASE_URL` 指向 test.db，`app.db.SessionLocal` 导入时即绑定。）

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_gateway.py -v`
Expected: FAIL（app.llm 不存在）

- [ ] **Step 3: 实现**

`server/app/config.py` 追加（顶部）：

```python
from dotenv import load_dotenv

load_dotenv()  # 读 server/.env（不入库），已存在的进程环境变量优先

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "fake-model")
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
```

（config.py 顶部补 `import os`。）

`server/app/llm/provider.py`：

```python
import json
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
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "max_tokens": self.max_tokens,
                  "messages": [{"role": "user", "content": prompt}]},
            transport=self.transport,
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
```

（provider.py 顶部需 `import os`；`default_fake_script` 放本文件尾。）

`server/app/llm/gateway.py`：

```python
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
```

`server/app/models.py` 追加（顶部 import 补 `Text`）：

```python
class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

依赖：`uv add httpx python-dotenv`（httpx 从 dev 组移到运行依赖：直接 add 即并存无害）。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（43+3=46）

- [ ] **Step 5: Alembic 迁移**

```bash
cd server && uv run alembic revision --autogenerate -m "llm_call_log"
uv run alembic upgrade head && sqlite3 skilllens.db ".tables"   # 含 llm_call_log
```

- [ ] **Step 6: Commit**

```bash
git add server/ && git commit -m "feat: LLM Gateway（OpenAI 兼容 + Fake 回退 + call_log 全量落库）"
```

---

### Task 2: 字段级 Before/After（reqBody 跨窗口确定性 diff）

**Files:**
- Create: `server/app/ingestion/fielddiff.py`（纯函数）、`server/app/ingestion/fieldchange.py`（服务）
- Modify: `server/app/models.py`（追加 FieldChange）、`server/app/api/llm_skills.py`（新 router，本任务先放 field-changes 端点）、`server/app/main.py`（挂载）
- Create: `server/alembic/versions/*_field_change.py`
- Test: `server/tests/test_fielddiff.py`

**Interfaces:**
- Consumes: 既有 `RawEvent`（network 事件 payload 含 `method/url/reqBody`）、`split_url/templatize_path`。
- Produces:
  - `flatten(obj: dict, prefix: str = "") -> dict[str, object]`：嵌套 dict 展平为点路径（`{"a":{"b":1}} → {"a.b":1}`；列表值原样保留不展开）；
  - `diff_bodies(before: dict, after: dict) -> list[dict]`：`[{"field","before","after"}]`（值不同的字段；一侧缺失记 `None`；标量与列表值直接比较）；
  - `extract_field_changes(db: Session, session_id: str) -> list[FieldChange]`：按 `(ts, seq)` 取该 session 全部 network 事件，按 API 模板分组，组内**相邻两次同模板 POST** 的 reqBody（JSON parse，失败跳过）做 diff，每组只取最后一次相邻对；幂等删旧插新；返回写入的行；
  - ORM `FieldChange`：`id`、`session_id` 索引、`api_template` str(500)、`before_seq`、`after_seq`、`changes` JSON、`created_at`；
  - `POST /api/v1/sessions/{session_id}/field-changes` → `{"field_changes": n}`（404 session 不存在）；`GET /api/v1/sessions/{session_id}/field-changes` → 行列表。
- T4 断言生成消费 FieldChange。

- [ ] **Step 1: 写失败测试**

`server/tests/test_fielddiff.py`：

```python
import json

from sqlalchemy import select


def test_flatten_nested():
    from app.ingestion.fielddiff import flatten
    assert flatten({"a": {"b": 1}, "c": "x"}) == {"a.b": 1, "c": "x"}


def test_diff_bodies_changes():
    from app.ingestion.fielddiff import diff_bodies
    changes = diff_bodies({"formName": "A", "keep": 1}, {"formName": "B", "keep": 1})
    assert changes == [{"field": "formName", "before": "A", "after": "B"}]


def test_diff_bodies_added_removed():
    from app.ingestion.fielddiff import diff_bodies
    changes = diff_bodies({"x": 1}, {"y": 2})
    assert {"field": "x", "before": 1, "after": None} in changes
    assert {"field": "y", "before": None, "after": 2} in changes


async def test_field_changes_endpoint(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 1, "ts": 100, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "reqBody": json.dumps({"formName": "v1"}),
                     "resBody": '{"code":200}'}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 300, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "reqBody": json.dumps({"formName": "v2", "extra": True}),
                     "resBody": '{"code":200}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    resp = await client.post(f"/api/v1/sessions/{sid}/field-changes")
    assert resp.status_code == 200 and resp.json() == {"field_changes": 1}

    rows = (await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()
    assert rows[0]["api_template"] == "/codeBack/formConfig/saveFormConfig"
    assert rows[0]["before_seq"] == 1 and rows[0]["after_seq"] == 3
    assert {"field": "formName", "before": "v1", "after": "v2"} in rows[0]["changes"]
    assert {"field": "extra", "before": None, "after": True} in rows[0]["changes"]

    # 幂等
    await client.post(f"/api/v1/sessions/{sid}/field-changes")
    assert len((await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_fielddiff.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/ingestion/fielddiff.py`：

```python
def flatten(obj: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in obj.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        else:
            out[key] = v
    return out


def diff_bodies(before: dict, after: dict) -> list[dict]:
    fb, fa = flatten(before), flatten(after)
    fields = sorted(set(fb) | set(fa))
    return [{"field": f, "before": fb.get(f), "after": fa.get(f)}
            for f in fields if fb.get(f) != fa.get(f)]
```

`server/app/ingestion/fieldchange.py`：

```python
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.url_template import split_url, templatize_path
from app.models import FieldChange, RawEvent


def extract_field_changes(db: Session, session_id: str) -> list[FieldChange]:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    posts: dict[str, list[tuple[int, dict]]] = {}
    for r in rows:
        p = r.payload or {}
        if r.kind != "network" or p.get("method") != "POST" or not p.get("reqBody"):
            continue
        try:
            body = json.loads(p["reqBody"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(body, dict):
            continue
        template, _ = templatize_path(split_url(p.get("url", ""))[0])
        posts.setdefault(template, []).append((r.seq, body))

    db.query(FieldChange).filter(FieldChange.session_id == session_id).delete()
    written: list[FieldChange] = []
    from app.ingestion.fielddiff import diff_bodies
    for template, seqs in posts.items():
        if len(seqs) < 2:
            continue
        (b_seq, b_body), (a_seq, a_body) = seqs[-2], seqs[-1]
        changes = diff_bodies(b_body, a_body)
        if not changes:
            continue
        row = FieldChange(session_id=session_id, api_template=template,
                          before_seq=b_seq, after_seq=a_seq, changes=changes)
        db.add(row)
        written.append(row)
    db.commit()
    return written
```

`server/app/models.py` 追加 `FieldChange`（字段见 Interfaces）。`server/app/api/llm_skills.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.fieldchange import extract_field_changes
from app.models import FieldChange, RecordingSession

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sessions/{session_id}/field-changes")
async def run_field_changes(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = extract_field_changes(db, session_id)
    return {"field_changes": len(rows)}


@router.get("/sessions/{session_id}/field-changes")
async def list_field_changes(session_id: str, db: Session = Depends(get_db)) -> list:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db.query(FieldChange).filter(FieldChange.session_id == session_id).all()
    return [{"api_template": r.api_template, "before_seq": r.before_seq,
             "after_seq": r.after_seq, "changes": r.changes} for r in rows]
```

main.py 挂载：`from app.api import events, ingest, llm_skills` + `app.include_router(llm_skills.router, prefix=API_PREFIX)`。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 51）

- [ ] **Step 5: Alembic 迁移 + Commit**

```bash
cd server && uv run alembic revision --autogenerate -m "field_change" && uv run alembic upgrade head
git add server/ && git commit -m "feat: 字段级 Before/After（同模板相邻 POST reqBody diff）"
```

---

### Task 3: Skill 归纳（LLM 命名 + 确定性回查降级）

**Files:**
- Create: `server/app/learning/__init__.py`（空）、`server/app/learning/skill.py`
- Modify: `server/app/models.py`（追加 Skill）、`server/app/api/llm_skills.py`（POST /alignments/{id}/induce + GET /skills）
- Create: `server/alembic/versions/*_skill.py`
- Test: `server/tests/test_skill.py`

**Interfaces:**
- Consumes: T1 `complete`；既有 `Alignment`（skeleton/param_variables/input_variables）。
- Produces:
  - `build_prompt(alignment: Alignment) -> str`：含骨架签名、变量名与值域样本、目标系统；要求 LLM 只返回 JSON `{"name": PascalCase 名, "description": "一句话中文"}`；
  - `parse_llm_skill(text: str) -> dict | None`：从 LLM 响应提取 JSON（容忍 ```json 代码块包裹；解析失败返回 None）；
  - `verify_skill(proposal: dict, alignment: Alignment) -> tuple[bool, str]`：确定性回查——name 非空且 PascalCase（`^[A-Z][A-Za-z0-9]*$`）、description 非空 ≤200 字符；通过返回 `(True, "")`；否则 `(False, 原因)`；
  - `induce_skill(db: Session, alignment_id: int) -> Skill`：取 alignment → build_prompt → complete(purpose="skill_naming") → parse → verify；失败则 name=`Candidate`、status=`candidate`、notes 记原因；成功 status=`learned`；confidence 确定性计算 = `骨架步数中含 API 的步数占比 * 0.6 + 变量识别到至少一个变量 * 0.4`（保留 2 位）；
  - ORM `Skill`：`id`、`alignment_id`（int，逻辑外键）、`name` str(100)、`description` Text、`status` str(20)（`learned|candidate`）、`skeleton` JSON（冗余存）、`param_variables` JSON、`input_variables` JSON、`confidence` float、`evidence_count` int（= session 数）、`notes` str(500) 默认 ""、`created_at`；同一 alignment_id 幂等删旧插新；
  - `POST /api/v1/alignments/{alignment_id}/induce` → Skill dict（404 alignment 不存在）；`GET /api/v1/skills` → 列表。
- T6 演示 2 消费。

- [ ] **Step 1: 写失败测试**

`server/tests/test_skill.py`：

```python
import json
import os

import pytest


@pytest.fixture
def fake_llm(monkeypatch):
    os.environ.pop("LLM_API_KEY", None)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormConfig", "description": "保存表单配置"}))


async def _make_alignment(client) -> int:
    sids = []
    for order_id in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 2000, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 2600, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    resp = await client.post("/api/v1/align", json={"session_ids": sids})
    return resp.json()["alignment_id"]


async def test_induce_learned(client, fake_llm):
    aid = await _make_alignment(client)
    resp = await client.post(f"/api/v1/alignments/{aid}/induce")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "SaveFormConfig"
    assert body["status"] == "learned"
    assert body["evidence_count"] == 2
    assert 0 < body["confidence"] <= 1
    assert len(body["skeleton"]) == 1


async def test_induce_candidate_on_bad_json(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "not-json")
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert body["name"] == "Candidate"
    assert "解析" in body["notes"] or "JSON" in body["notes"]


async def test_induce_candidate_on_bad_name(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "save form", "description": "x"}))
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert "PascalCase" in body["notes"]


async def test_induce_idempotent(client, fake_llm):
    aid = await _make_alignment(client)
    await client.post(f"/api/v1/alignments/{aid}/induce")
    await client.post(f"/api/v1/alignments/{aid}/induce")
    skills = (await client.get("/api/v1/skills")).json()
    assert len([s for s in skills if s["alignment_id"] == aid]) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_skill.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/learning/skill.py`：

```python
import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import Alignment, Skill

PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def build_prompt(alignment: Alignment) -> str:
    lines = ["你在分析一个企业软件中被用户反复执行的操作流程。请为它命名。"]
    lines.append("流程骨架（每步一个签名）:")
    for step in alignment.skeleton:
        lines.append(f"  - {step['signature']}")
    if alignment.input_variables:
        names = ", ".join(v["name"] for v in alignment.input_variables)
        lines.append(f"输入变量: {names}")
    if alignment.param_variables:
        names = ", ".join(v["param"] for v in alignment.param_variables)
        lines.append(f"API 参数变量: {names}")
    lines.append('只返回 JSON，不要任何其他文字: {"name": "PascalCase 英文名", "description": "一句话中文描述"}')
    return "\n".join(lines)


def parse_llm_skill(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def verify_skill(proposal: dict, alignment: Alignment) -> tuple[bool, str]:
    name = str(proposal.get("name") or "")
    desc = str(proposal.get("description") or "")
    if not PASCAL.match(name):
        return False, "name 必须是 PascalCase（首字母大写无空格）"
    if not desc or len(desc) > 200:
        return False, "description 必须非空且 ≤200 字符"
    return True, ""


def _confidence(alignment: Alignment) -> float:
    api_steps = sum(1 for s in alignment.skeleton if "|" in s.get("signature", ""))
    total = max(len(alignment.skeleton), 1)
    has_vars = 1.0 if (alignment.param_variables or alignment.input_variables) else 0.0
    return round(api_steps / total * 0.6 + has_vars * 0.4, 2)


def induce_skill(db: Session, alignment_id: int) -> Skill:
    alignment = db.get(Alignment, alignment_id)
    result = complete(db, "skill_naming", build_prompt(alignment))
    proposal = parse_llm_skill(result.text)
    status, name, desc, notes = "candidate", "Candidate", "", ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        ok, why = verify_skill(proposal, alignment)
        if ok:
            status, name, desc = "learned", proposal["name"], proposal["description"]
        else:
            notes = why
    confidence = _confidence(alignment)
    db.query(Skill).filter(Skill.alignment_id == alignment_id).delete()
    skill = Skill(
        alignment_id=alignment_id, name=name, description=desc, status=status,
        skeleton=alignment.skeleton, param_variables=alignment.param_variables,
        input_variables=alignment.input_variables, confidence=confidence,
        evidence_count=len(alignment.session_ids), notes=notes,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill
```

（models.py 的 `Skill` 字段见 Interfaces；`alignment_id: Mapped[int] = mapped_column(index=True)`。）

llm_skills.py 追加：

```python
from app.learning.skill import induce_skill
from app.models import Skill


@router.post("/alignments/{alignment_id}/induce")
async def induce(alignment_id: int, db: Session = Depends(get_db)) -> dict:
    from app.models import Alignment
    if not db.get(Alignment, alignment_id):
        raise HTTPException(status_code=404, detail="alignment not found")
    skill = induce_skill(db, alignment_id)
    return {"id": skill.id, "alignment_id": skill.alignment_id, "name": skill.name,
            "description": skill.description, "status": skill.status,
            "skeleton": skill.skeleton, "param_variables": skill.param_variables,
            "input_variables": skill.input_variables, "confidence": skill.confidence,
            "evidence_count": skill.evidence_count, "notes": skill.notes}


@router.get("/skills")
async def list_skills(db: Session = Depends(get_db)) -> list:
    rows = db.query(Skill).order_by(Skill.id.desc()).all()
    return [{"id": r.id, "alignment_id": r.alignment_id, "name": r.name,
             "description": r.description, "status": r.status,
             "confidence": r.confidence, "evidence_count": r.evidence_count,
             "notes": r.notes} for r in rows]
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 55）

- [ ] **Step 5: Alembic 迁移 + Commit**

```bash
cd server && uv run alembic revision --autogenerate -m "skill" && uv run alembic upgrade head
git add server/ && git commit -m "feat: Skill 归纳（LLM 命名 + 确定性回查，失败降级 candidate）"
```

---

### Task 4: Outcome 断言生成与回放验证

**Files:**
- Create: `server/app/learning/outcome.py`
- Modify: `server/app/models.py`（追加 OutcomeAssertion）、`server/app/api/llm_skills.py`（POST /skills/{id}/assertions + POST /assertions/{id}/verify）
- Create: `server/alembic/versions/*_outcome_assertion.py`
- Test: `server/tests/test_outcome.py`

**Interfaces:**
- Consumes: T3 `Skill`（skeleton/session 来源经 alignment_id 回查）、T2 `FieldChange`、既有 `semantic_action.state_signals`。
- Produces:
  - `generate_assertions(db: Session, skill_id: int) -> list[OutcomeAssertion]`：对 skill 的 alignment 的每个 session 生成断言（无 LLM）：
    - 层 3 断言：skeleton 每个含 API 的步 → 对应窗口每个 API call 生成 `{"layer": 3, "kind": "api_status", "api_template": ..., "expect_status": 200}`；
    - 层 3 状态断言：窗口 state_signals 非空的 `{"layer": 3, "kind": "state_signal", "api_template": ..., "field": ..., "expect_value": ...}`；
    - 层 2 断言：session 的 FieldChange 每条 change 生成 `{"layer": 2, "kind": "field_change", "api_template": ..., "field": ..., "before": ..., "after": ...}`；
    断言行：`id`、`skill_id` 索引、`layer` int、`kind` str(30)、`api_template` str(500)、`payload` JSON（含 expect/field/before/after）、`created_at`；按 skill_id 幂等删旧插新；
  - `verify_against_session(db: Session, assertion_id: int) -> dict`：重放验证——按断言 kind 重查该 skill 的 alignment 的**每个** session 的实际数据（api_status：semantic_action.api_calls 里该模板 status；state_signal：state_signals；field_change：FieldChange.changes），全部 session 满足 → `{"passed": true, "sessions_checked": n}`，任一不满足 → `{"passed": false, "failed_sessions": [...]}`；404 断言不存在；
  - 端点：`POST /api/v1/skills/{skill_id}/assertions` → `{"assertions": n}`；`POST /api/v1/assertions/{assertion_id}/verify` → verify 结果；`GET /api/v1/skills/{skill_id}/assertions` → 列表。

- [ ] **Step 1: 写失败测试**

`server/tests/test_outcome.py`：

```python
import json


async def _make_learned_skill(client, monkeypatch) -> tuple[int, str]:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveOrder", "description": "保存订单"}))
    sids = []
    for oid in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 100, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 300, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": json.dumps({"note": f"n{oid}"}),
                         "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        await client.post(f"/api/v1/sessions/{sid}/field-changes")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"], sids[0]


async def test_generate_assertions(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    resp = await client.post(f"/api/v1/skills/{skill_id}/assertions")
    assert resp.status_code == 200
    n = resp.json()["assertions"]
    assert n >= 3  # api_status + state_signal + field_change
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"api_status", "state_signal", "field_change"}


async def test_verify_all_pass(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    for r in rows:
        result = (await client.post(f"/api/v1/assertions/{r['id']}/verify")).json()
        assert result["passed"] is True, r


async def test_verify_detects_failure(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    # 直接改库造一个失败：删除第一个 session 的 field_change
    from app.db import SessionLocal
    from app.models import FieldChange
    db = SessionLocal()
    db.query(FieldChange).filter(FieldChange.session_id ==
                                 (await _first_alignment_session(client, skill_id))).delete()
    db.commit()
    db.close()
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    fc = next(r for r in rows if r["kind"] == "field_change")
    result = (await client.post(f"/api/v1/assertions/{fc['id']}/verify")).json()
    assert result["passed"] is False


async def _first_alignment_session(client, skill_id):
    from app.db import SessionLocal
    from app.models import Alignment, Skill
    db = SessionLocal()
    skill = db.get(Skill, skill_id)
    sids = skill.input_variables and [] or []
    alignment = db.get(Alignment, skill.alignment_id)
    db.close()
    return alignment.session_ids[0]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_outcome.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/learning/outcome.py`：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, FieldChange, OutcomeAssertion, SemanticAction, Skill


def generate_assertions(db: Session, skill_id: int) -> list[OutcomeAssertion]:
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    rows: list[OutcomeAssertion] = []
    for sid in alignment.session_ids:
        actions = db.execute(
            select(SemanticAction).where(SemanticAction.session_id == sid)
        ).scalars().all()
        for action in actions:
            for call in action.api_calls or []:
                rows.append(("api_status", call["template"], 3,
                             {"api_template": call["template"], "expect_status": call.get("status")}))
            for sig in action.state_signals or []:
                rows.append(("state_signal", sig["api"], 3,
                             {"api_template": sig["api"], "field": sig["field"],
                              "expect_value": sig["value"]}))
        changes = db.execute(
            select(FieldChange).where(FieldChange.session_id == sid)
        ).scalars().all()
        for fc in changes:
            for ch in fc.changes:
                rows.append(("field_change", fc.api_template, 2,
                             {"api_template": fc.api_template, "field": ch["field"],
                              "before": ch["before"], "after": ch["after"]}))

    # 按 (kind, api_template, field) 去重（跨 session 重复的同类断言合并）
    seen: dict[tuple, tuple] = {}
    for kind, tpl, layer, payload in rows:
        seen.setdefault((kind, tpl, payload.get("field", "")), (kind, tpl, layer, payload))

    db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).delete()
    written = []
    for kind, tpl, layer, payload in seen.values():
        row = OutcomeAssertion(skill_id=skill_id, layer=layer, kind=kind,
                               api_template=tpl, payload=payload)
        db.add(row)
        written.append(row)
    db.commit()
    return written


def verify_against_session(db: Session, assertion_id: int) -> dict:
    a = db.get(OutcomeAssertion, assertion_id)
    skill = db.get(Skill, a.skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    p = a.payload
    failed: list[str] = []
    for sid in alignment.session_ids:
        ok = _check_one(db, sid, a.kind, p)
        if not ok:
            failed.append(sid)
    return {"passed": not failed, "sessions_checked": len(alignment.session_ids),
            "failed_sessions": failed}


def _check_one(db: Session, sid: str, kind: str, p: dict) -> bool:
    if kind == "api_status":
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        statuses = [c.get("status") for act in actions for c in (act.api_calls or [])
                    if c.get("template") == p["api_template"]]
        return bool(statuses) and all(s == p["expect_status"] for s in statuses)
    if kind == "state_signal":
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        values = [s["value"] for act in actions for s in (act.state_signals or [])
                  if s["api"] == p["api_template"] and s["field"] == p["field"]]
        return bool(values) and all(v == p["expect_value"] for v in values)
    if kind == "field_change":
        fcs = db.execute(select(FieldChange).where(FieldChange.session_id == sid)).scalars().all()
        for fc in fcs:
            for ch in fc.changes:
                if (fc.api_template == p["api_template"] and ch["field"] == p["field"]
                        and ch["before"] == p["before"] and ch["after"] == p["after"]):
                    return True
        return False
    return False
```

（models.py 的 `OutcomeAssertion`：`id`、`skill_id` 索引、`layer` int、`kind` str(30)、`api_template` str(500)、`payload` JSON、`created_at`。端点按 Interfaces 补进 llm_skills.py。）

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 58）

- [ ] **Step 5: Alembic 迁移 + Commit**

```bash
cd server && uv run alembic revision --autogenerate -m "outcome_assertion" && uv run alembic upgrade head
git add server/ && git commit -m "feat: Outcome 层2/3 断言生成与跨 session 回放验证"
```

---

### Task 5: 清理小项 + .env.example 提交

**Files:**
- Create: `server/.env.example`（若已存在则确认内容为占位值）
- Modify: `server/app/api/events.py`（409 文案）、`server/app/ingestion/alignment.py`（ref_sid 死变量删除）

**Interfaces:** 无新接口；纯清理。

- [ ] **Step 1: 三处小修**

`server/app/api/events.py` 409 分支 detail 改为 `"duplicate (session_id, page_id, seq)"`。

`server/app/ingestion/alignment.py` 删除未使用的 `ref_sid, _ = sig_lists[0]` 行（保留 `ref = sig_lists[0][1]` 语义，改为 `ref = sig_lists[0][1]`）。

确认 `server/.env.example` 存在且全部是占位值（真实 key 绝不入库：`git grep "sk-WGc7" || true` 必须无输出）。

- [ ] **Step 2: 测试 + Commit**

Run: `cd server && uv run pytest tests/ -q` → 全部 passed

```bash
git add server/ && git commit -m "chore: 409 文案三列化、死变量清理、.env.example"
```

---

### Task 6: njmind E2E（真实 LLM 首跑 + 演示 2：Skill 卡片）

**Files:**
- Create: `demo/sprint3/README.md`、`demo/sprint3/skill-card.txt`

**Interfaces:**
- Consumes: 全部前序任务；`server/.env`（真实 key，用户已配置）。
- Produces: Sprint 3 验收证据。

- [ ] **Step 1: 启动（server 加载 .env）**

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
```

（config.py 的 `load_dotenv()` 在 import 时读取 server/.env，无需额外参数。）

- [ ] **Step 2: 真实 LLM 连通性冒烟（我执行）**

```bash
curl -s http://127.0.0.1:8710/api/v1/health
# 用户已做两次演示（Sprint 2 的 426c3da9/f007da25 已 process+align，alignment_id=1）
curl -s -X POST http://127.0.0.1:8710/api/v1/alignments/1/induce
```

- [ ] **Step 3: 用户操作（人工）**

用 njmind 再做两次演示（输入不同值），或直接复用 Sprint 2 的两次演示数据（alignment 已存在，推荐复用）。如需新数据：popup 开录 → 改字段值 → 保存 → 停止，做两次。

- [ ] **Step 4: 验收（逐项确认）**

1. `llm_call_log` 有 ≥1 行真实记录（provider=openai-compat、model=qwen 系、prompt/response 非空）；
2. induce 返回 `status=learned` 且 name 是合理 PascalCase（如 `SaveFormConfig`）——真实 LLM 命名质量验收；
3. Skill 卡片字段齐全（skeleton/confidence/evidence_count=2/variables）；
4. `POST /skills/{id}/assertions` 生成 ≥3 条断言，覆盖三种 kind；
5. 全部断言 `verify` passed=true；
6. 对 Sprint 2 数据跑 field-changes（426c3da9 有两次保存）：若两次保存间表单配置有差异则 diff 出 `字段: A→B`；无差异则空（语义正确）；
7. Fake 路径回归：无 key 时（`LLM_API_KEY="" python -c` 快速验证或单测已覆盖）Gateway 回退不报错。

- [ ] **Step 5: 记录证据并提交**

```bash
git add demo/sprint3/ && git commit -m "test: Sprint 3 E2E 验收（真实 LLM 命名 + Skill 卡片 + 断言回放）" && git push
```

- [ ] **Step 6: Sprint 回顾**

对照 spec §12（重点 #8：LLM 产物是否全部过确定性回查；#1/#9 主线与测试全绿）；确认演示 2 达成（Skill 卡片含证据计数与置信度）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.4 LLM Gateway（Provider 可替换、call_log 全量、客户自带 key）→ T1；§4.3 Skill 归纳（LLM 命名+回查降级 candidate、confidence/evidence_count）→ T3；§4.3 层 2 字段级 Before/After（用户 2026-09-24 裁定）→ T2；层 2/3 断言生成与回放 → T4（spec §7 Sprint 3 验收"断言能在原始 Episode 上回放验证通过"）；演示 2 Skill 卡片 → T6；终审清理小项（409 文案/ref_sid）→ T5。未覆盖（Sprint 4+）：插件侧 Before/After 状态快照（spec §4.3 层 2(b)）、Replay Runner、Expected Delta。
- **占位符**：无 TBD；T3/T4 端点代码完整；T4 测试的 `_first_alignment_session` 辅助函数已给出实现。
- **类型一致性**：`complete(db, purpose, prompt)` 在 T1 定义、T3 消费一致；`induce_skill(db, alignment_id)` 与端点一致；`generate_assertions/verify_against_session(db, assertion_id)` 与端点一致；FieldChange/OutcomeAssertion 字段名在 T2/T4 与测试 JSON 键一致；`llm_call_log` 表名与既有 spec §5 一致。
- **已知取舍**：confidence 公式为拍定的启发式（0.6/0.4 权重，spec 未定数值，Sprint 4 用真实数据校准）；断言跨 session 去重合并（同类断言一份）；verify 的 field_change 要求 before/after 精确匹配（严格语义，Drift 检测留 Sprint 5）。
- **安全**：真实 key 仅在 server/.env（gitignore 已验证）；.env.example 全占位；计划与测试均不含真实值。


