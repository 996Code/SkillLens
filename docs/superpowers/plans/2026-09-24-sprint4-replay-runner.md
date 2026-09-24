# Sprint 4 实施计划：Replay Runner（语义定位 + 换参数回放 + PASS/FAIL + 影子模式）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 learned 的 Skill 编译成回放计划并用 Playwright 语义定位执行：换参数注入、网络观察复用 Outcome 断言做确定性 PASS/FAIL、C1 影子模式（含 POST 未确认一律影子）。

**Architecture:** runner 以**进程内模块** `server/app/replay/` 落地（spec §6 的独立进程+任务队列是 Phase 3 形态，MVP 用 FastAPI 端点内联执行——裁定记录于本节）；回放计划从参考 session 的 action 事件序列编译（click→label、input→name/value，变量经 overrides 注入）；执行用 Playwright async + 语义定位链（role→text→placeholder→name，不录 CSS selector）；网络观察用 page.on("response") 捕获 status/body，`path_matches` 把实际 URL 匹配回断言的 API 模板；浏览器测试全离线（`page.set_content` + `page.route` mock API 响应）。

**Tech Stack:** 既有栈 + `playwright`（async API，chromium）。基线：pytest 59、vitest 19。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md`（§4.5 Replay Runner、§7 Sprint 4 行、§2 约束 C1）

## Global Constraints（每个任务默认遵守）

- **C1 逐字**：`side_effect: none | resettable | destructive`，`destructive` 一律走影子模式——MVP 确定性规则：**骨架签名含 `POST:` 且未传 `confirm_side_effect=true` → 强制 shadow（不打开浏览器、只编译计划落库）**。
- 语义定位**禁止 CSS selector**：定位链 role(button/link)→text→placeholder→name/label，记录每步命中的策略名。
- PASS/FAIL **只由断言比对得出**（确定性）；LLM 仅在 FAIL 时做归因（purpose=`replay_failure_attribution`），不参与判定。
- 回放计划、执行结果、断言结果、归因全部落 `replay_run`（C3）。
- 浏览器单测**全离线**：`set_content` + `page.route` mock，不访问 njmind/外网。
- server 完成标准 = `cd server && uv run pytest tests/ -v` 全过；提交信息中文 `feat|test|chore|fix: 描述`。
- Playwright 安装：`uv add playwright` + `uv run playwright install chromium`（T1 执行一次）。
- njmind 真实回放由用户在 T5 配合（提供可重置的测试表单 URL）。

## File Structure

```text
server/app/replay/__init__.py
server/app/replay/plan.py           # T1 compile_replay_plan + requires_confirmation（纯函数）
server/app/replay/locate.py         # T2 semantic_locator（浏览器依赖）
server/app/replay/runner.py         # T2 execute_plan/observe；T3 run_replay 编排；T4 screenshot+归因
server/app/replay/assert_eval.py    # T2 path_matches + evaluate_assertions（纯函数）
server/app/models.py                # T1 ReplayRun
server/alembic/versions/*_replay_run.py
server/app/api/replay.py            # T3 POST /skills/{id}/replay + GET /replay-runs/{id}
server/tests/test_replay_plan.py    # T1
server/tests/test_assert_eval.py    # T2（纯函数部分）
server/tests/test_runner_browser.py # T2（Playwright 离线）
server/tests/test_replay_api.py     # T3（monkeypatch runner）
server/tests/test_replay_failure.py # T4（FAIL→截图+归因）
demo/sprint4/                       # T5
```

---

### Task 1: 回放计划编译 + C1 门控规则（纯函数）+ ReplayRun 落库

**Files:**
- Create: `server/app/replay/__init__.py`（空）、`server/app/replay/plan.py`
- Modify: `server/app/models.py`（追加 ReplayRun）
- Create: `server/alembic/versions/*_replay_run.py`
- Test: `server/tests/test_replay_plan.py`

**Interfaces:**
- Consumes: `RawEvent` 行形态的 dict（`{seq, ts, kind, payload}`）与 `Skill.skeleton`。
- Produces:
  - `compile_replay_plan(events: list[dict], overrides: dict[str, str]) -> dict`：`{"url": str, "steps": [{"kind": "click"|"input", "label"?, "name"?, "value"?, "original_value"?}]}`——click 取 `payload.target.label`（空 label 丢弃）；input 取 `payload.name`，value 优先 `overrides[name]`（记 `original_value`）；url 取首个 navigation 事件的 `payload.url`；
  - `requires_confirmation(skill_skeleton: list[dict]) -> bool`：任一步 signature 含 `"POST:"` → True；
  - ORM `ReplayRun`：`id`、`skill_id` 索引、`mode` str(10)（`execute|shadow`）、`status` str(10)（`pass|fail|error|shadow`）、`plan` JSON、`executed` JSON nullable、`assertion_results` JSON nullable、`attribution` Text nullable、`artifact_path` str(300) 默认 ""、`created_at`。
- T2/T3 消费。

- [ ] **Step 1: 安装依赖（一次性）**

```bash
cd server && uv add playwright && uv run playwright install chromium
```

- [ ] **Step 2: 写失败测试**

`server/tests/test_replay_plan.py`：

```python
from app.replay.plan import compile_replay_plan, requires_confirmation


def ev(kind, ptype=None, **payload):
    return {"seq": 0, "ts": 0, "kind": kind,
            "payload": {"type": ptype, **payload} if ptype else payload}


EVENTS = [
    ev("navigation", "page-load", url="http://t/form"),
    ev("action", "click", target={"label": "请输入"}),
    ev("action", "input", name="请输入", value="旧值"),
    ev("action", "click", target={"label": ""}),          # 空 label 丢弃
    ev("action", "click", target={"label": "保存"}),
]


def test_compile_clicks_and_inputs():
    plan = compile_replay_plan(EVENTS, {})
    assert plan["url"] == "http://t/form"
    assert plan["steps"] == [
        {"kind": "click", "label": "请输入"},
        {"kind": "input", "name": "请输入", "value": "旧值", "original_value": "旧值"},
        {"kind": "click", "label": "保存"},
    ]


def test_compile_override_injects_value():
    plan = compile_replay_plan(EVENTS, {"请输入": "新值888"})
    step = plan["steps"][1]
    assert step["value"] == "新值888" and step["original_value"] == "旧值"


def test_requires_confirmation_on_post():
    assert requires_confirmation([{"signature": "click:保存|POST:/a/save"}]) is True
    assert requires_confirmation([{"signature": "click:查"}]) is False
    assert requires_confirmation([]) is False
```

- [ ] **Step 3: 运行确认失败**

Run: `cd server && uv run pytest tests/test_replay_plan.py -v` → FAIL（模块不存在）

- [ ] **Step 4: 实现**

`server/app/replay/plan.py`：

```python
def compile_replay_plan(events: list[dict], overrides: dict[str, str]) -> dict:
    url = ""
    steps: list[dict] = []
    for e in events:
        payload = e.get("payload") or {}
        if e["kind"] == "navigation" and not url:
            url = payload.get("url", "")
        if e["kind"] != "action":
            continue
        if payload.get("type") == "click":
            label = (payload.get("target") or {}).get("label") or ""
            if label:
                steps.append({"kind": "click", "label": label})
        elif payload.get("type") == "input":
            name = payload.get("name") or ""
            original = str(payload.get("value", ""))
            steps.append({"kind": "input", "name": name,
                          "value": str(overrides.get(name, original)),
                          "original_value": original})
    return {"url": url, "steps": steps}


def requires_confirmation(skill_skeleton: list[dict]) -> bool:
    return any("POST:" in (step.get("signature") or "") for step in skill_skeleton)
```

`server/app/models.py` 追加 `ReplayRun`（字段见 Interfaces）。

- [ ] **Step 5: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（59+3=62）

- [ ] **Step 6: Alembic 迁移 + Commit**

```bash
cd server && uv run alembic revision --autogenerate -m "replay_run" && uv run alembic upgrade head
git add server/ && git commit -m "feat: 回放计划编译与 C1 门控规则（含 POST 未确认不放行）"
```

---

### Task 2: 语义定位执行器 + 断言求值（Playwright 离线全测）

**Files:**
- Create: `server/app/replay/locate.py`、`server/app/replay/runner.py`、`server/app/replay/assert_eval.py`
- Test: `server/tests/test_assert_eval.py`、`server/tests/test_runner_browser.py`

**Interfaces:**
- Consumes: T1 `compile_replay_plan` 产出的 plan dict；既有 `OutcomeAssertion.payload`（api_template/expect_status/expect_value/field）。
- Produces:
  - `locate(page, label: str) -> tuple[Locator, str]`：定位链依次尝试（返回首个命中且 visible 的）：`page.get_by_role("button", name=label)` → `page.get_by_text(label, exact=True)` → `page.get_by_placeholder(label)` → `page.get_by_label(label)`；返回 `(locator, strategy)`；
  - `path_matches(url: str, template: str) -> bool`：把 template 的 `{id}` 段还原为通配（`\d+|[0-9a-f-]{36}`），比对 url path；query 忽略；
  - `evaluate_assertions(assertions: list[dict], observed: list[dict]) -> list[dict]`：输入断言 payload 列表与观察列表 `{"url","status","body"}`，输出逐断言 `{"payload", "observed_status"|None, "passed": bool}`——api_status：存在 path_matches 的观察且 status 全等；state_signal：body JSON 提取 field 路径值全等（field 支持点路径一层）；
  - `execute_plan(browser_page, plan: dict, api_mocks: dict[str, int] | None = None) -> dict`：返回 `{"executed": [{"step", "strategy"|None, "ok", "error"?}], "observed": [{"url","status","body"}]}`——逐 step：click→locate+click；input→locate（input 框同链）+fill；`page.on("response")` 收集观察（body 限 8KB）；**任何 step 定位失败即停**，后续步骤标 `{"ok": false, "error": "not attempted"}`；
  - T3 编排与 T4 归因消费。

- [ ] **Step 1: 写失败测试（纯函数）**

`server/tests/test_assert_eval.py`：

```python
from app.replay.assert_eval import evaluate_assertions, path_matches


def test_path_matches_templated():
    assert path_matches("http://h/orders/92382/save?x=1", "/orders/{id}/save") is True
    assert path_matches("http://h/orders/abc/save", "/orders/{id}/save") is False


def test_evaluate_api_status():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    observed = [{"url": "http://h/a/1/save", "status": 200, "body": ""},
                {"url": "http://h/other", "status": 500, "body": ""}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True and result[0]["observed_status"] == 200


def test_evaluate_api_status_missing():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    result = evaluate_assertions(assertions, [{"url": "http://h/b", "status": 200, "body": ""}])
    assert result[0]["passed"] is False and result[0]["observed_status"] is None


def test_evaluate_state_signal():
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/a/save", "field": "code", "expect_value": 200}}]
    observed = [{"url": "http://h/a/save", "status": 200, "body": '{"code":200,"data":{"state":"OK"}}'}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True
```

- [ ] **Step 2: 写失败测试（Playwright 离线）**

`server/tests/test_runner_browser.py`：

```python
import json

import pytest
from playwright.async_api import async_playwright

from app.replay.runner import execute_plan

FORM_HTML = """
<html><body>
  <input placeholder="请输入" />
  <button role="button">保存</button>
</body></html>
"""


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.mark.asyncio
async def test_execute_plan_semantic_locate():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(FORM_HTML)
        calls = []
        await page.route("**/api/save", lambda route: (
            calls.append(route.request.url), route.fulfill(status=200, body='{"code":200}')))
        plan = {"url": "about:blank", "steps": [
            {"kind": "input", "name": "请输入", "value": "v1", "original_value": "o"},
            {"kind": "click", "label": "保存"},
        ]}
        # 注入一个真实触发 fetch 的按钮行为
        await page.evaluate("""() => {
          document.querySelector('button').addEventListener('click',
            () => fetch('/api/save', {method: 'POST'}));
        }""")
        result = await execute_plan(page, plan)
        await browser.close()
    assert [s["ok"] for s in result["executed"]] == [True, True]
    assert result["executed"][0]["strategy"] in ("placeholder",)
    assert len(result["observed"]) == 1 and result["observed"][0]["status"] == 200


@pytest.mark.asyncio
async def test_execute_plan_stops_on_missing_element():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(FORM_HTML)
        plan = {"url": "about:blank", "steps": [
            {"kind": "click", "label": "不存在的按钮"},
            {"kind": "click", "label": "保存"},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert result["executed"][0]["ok"] is False
    assert result["executed"][1]["ok"] is False and result["executed"][1]["error"] == "not attempted"
```

（文件顶部 `import asyncio`。若 `pytest.mark.asyncio` 与模块级 event_loop fixture 在现有 asyncio_mode=auto 下冲突，去掉 `@pytest.mark.asyncio` 装饰器即可——auto 模式自动收集 async 测试。）

- [ ] **Step 3: 运行确认失败**

Run: `cd server && uv run pytest tests/test_assert_eval.py tests/test_runner_browser.py -v` → FAIL（模块不存在）

- [ ] **Step 4: 实现**

`server/app/replay/assert_eval.py`：

```python
import json
import re


def path_matches(url: str, template: str) -> bool:
    pattern = ""
    for seg in template.split("/"):
        pattern += ("/" if pattern else "") + (
            r"(?:\d+|[0-9a-fA-F-]{36})" if seg == "{id}" else re.escape(seg))
    m = re.search(pattern + r"(?:\?|$)", url)
    return m is not None


def _extract_field(body: str, field: str) -> object:
    try:
        node = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    for part in field.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def evaluate_assertions(assertions: list[dict], observed: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in assertions:
        p = a["payload"]
        matched = [o for o in observed if path_matches(o["url"], p["api_template"])]
        if a["kind"] == "api_status":
            statuses = [o["status"] for o in matched]
            passed = bool(statuses) and all(s == p["expect_status"] for s in statuses)
            out.append({"payload": p, "observed_status": statuses[0] if statuses else None,
                        "passed": passed})
        elif a["kind"] == "state_signal":
            values = [_extract_field(o.get("body", ""), p["field"]) for o in matched]
            passed = bool(matched) and all(v == p["expect_value"] for v in values)
            out.append({"payload": p, "observed_status": matched[0]["status"] if matched else None,
                        "passed": passed})
        else:  # field_change：回放时无 before/after 语义，跳过
            out.append({"payload": p, "observed_status": None, "passed": True,
                        "skipped": "field_change 不在回放中判定"})
    return out
```

`server/app/replay/locate.py`：

```python
from playwright.async_api import Locator, Page


async def locate(page: Page, label: str) -> tuple[Locator, str]:
    candidates: list[tuple[Locator, str]] = [
        (page.get_by_role("button", name=label), "role-button"),
        (page.get_by_text(label, exact=True), "text"),
        (page.get_by_placeholder(label), "placeholder"),
        (page.get_by_label(label), "label"),
    ]
    for locator, strategy in candidates:
        try:
            if await locator.count() > 0 and await locator.first.is_visible():
                return locator.first, strategy
        except Exception:
            continue
    raise LookupError(f"semantic locate failed: {label!r}")
```

`server/app/replay/runner.py`：

```python
import json

from playwright.async_api import Page

from app.replay.locate import locate

MAX_BODY = 8192


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000) -> dict:
    observed: list[dict] = []

    async def on_response(response):
        try:
            body = await response.text()
        except Exception:
            body = ""
        observed.append({"url": response.url, "status": response.status,
                         "body": body[:MAX_BODY]})

    page.on("response", on_response)
    executed: list[dict] = []
    failed = False
    for step in plan.get("steps", []):
        if failed:
            executed.append({**step, "ok": False, "error": "not attempted"})
            continue
        try:
            if step["kind"] == "click":
                locator, strategy = await locate(page, step["label"])
                await locator.click(timeout=timeout_ms)
                executed.append({**step, "strategy": strategy, "ok": True})
            elif step["kind"] == "input":
                locator, strategy = await locate(page, step["name"])
                await locator.fill(step["value"], timeout=timeout_ms)
                executed.append({**step, "strategy": strategy, "ok": True})
            else:
                executed.append({**step, "ok": False, "error": f"unknown kind {step['kind']}"})
                failed = True
        except Exception as exc:
            executed.append({**step, "ok": False, "error": str(exc)[:200]})
            failed = True
    try:
        await page.wait_for_timeout(500)  # 收尾等待尾随响应
    except Exception:
        pass
    return {"executed": executed, "observed": observed}
```

- [ ] **Step 5: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（62+6=68 左右）

- [ ] **Step 6: Commit**

```bash
git add server/ && git commit -m "feat: 语义定位执行器与断言求值（Playwright 离线全测）"
```

---

### Task 3: 回放编排 + 端点（C1 影子门控落地）

**Files:**
- Modify: `server/app/replay/runner.py`（追加 run_replay 编排）、`server/app/api/`（新 replay.py router）、`server/app/main.py`（挂载）
- Test: `server/tests/test_replay_api.py`（monkeypatch execute_plan，不起浏览器）

**Interfaces:**
- Consumes: T1 `compile_replay_plan/requires_confirmation/ReplayRun`、T2 `execute_plan/evaluate_assertions`、既有 `Skill/OutcomeAssertion/Alignment/RawEvent`。
- Produces:
  - `async run_replay(db, skill_id: int, overrides: dict[str, str], confirm_side_effect: bool) -> ReplayRun`：流程——取 Skill+Alignment → 取参考 session（session_ids[0]）原始事件 → compile_replay_plan → `requires_confirmation(skill.skeleton) and not confirm_side_effect` → **shadow 模式**（不启浏览器，status=`shadow`，executed=None）→ 否则启动 chromium 执行 execute_plan → 断言集 = `OutcomeAssertion` where skill_id → evaluate → status=`pass`（全部 passed）/`fail`（有 failed）/`error`（所有 step not ok）→ 落库 ReplayRun；
  - `POST /api/v1/skills/{skill_id}/replay` body `{"overrides": {字段名: 新值}, "confirm_side_effect": false}` → ReplayRun dict（404 skill 不存在；shadow 时响应含 `"mode": "shadow"` 提示需确认）；`GET /api/v1/replay-runs/{id}` → 详情；
  - 浏览器启停：`run_replay` 内 `async with async_playwright() as p: browser = await p.chromium.launch(); page = await browser.new_page(); await page.goto(plan["url"])`。

- [ ] **Step 1: 写失败测试（monkeypatch execute_plan）**

`server/tests/test_replay_api.py`：

```python
import json

import app.replay.runner as runner_mod


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


async def test_shadow_mode_without_confirmation(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fail_if_called(*a, **k):
        raise AssertionError("shadow mode must not launch browser")
    monkeypatch.setattr(runner_mod, "execute_plan", fail_if_called)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "shadow" and body["status"] == "shadow"
    assert body["executed"] is None and body["plan"]["steps"]  # 计划已编译落库


async def test_execute_mode_pass(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"code":200}'}]}

    class FakePage:
        async def goto(self, url): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
    class FakeBrowser:
        async def new_page(self): return FakePage()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    import app.replay.runner as rm
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())   # runner 内部浏览器入口（见实现）

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {"请输入": "新值"}, "confirm_side_effect": True})
    body = resp.json()
    assert body["mode"] == "execute" and body["status"] == "pass"
    assert body["plan"]["steps"][0]["value"] == "新值"       # override 注入
    assert all(r["passed"] for r in body["assertion_results"])


async def test_replay_run_get_404(client):
    resp = await client.get("/api/v1/replay-runs/9999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_replay_api.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/replay/runner.py` 追加：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.learning.outcome import evaluate_assertions as _unused_placeholder  # noqa: F401（删除此行，断言求值从 assert_eval import）
```

（以文件实际形态做等效追加，正确 import 为：）

```python
from playwright.async_api import async_playwright

from app.models import Alignment, OutcomeAssertion, RawEvent, ReplayRun, Skill
from app.replay.assert_eval import evaluate_assertions
from app.replay.plan import compile_replay_plan, requires_confirmation


def _launch():
    return async_playwright()


async def run_replay(db: Session, skill_id: int, overrides: dict[str, str],
                     confirm_side_effect: bool) -> ReplayRun:
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(select(RawEvent).where(RawEvent.session_id == ref_sid)
                      .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind, "payload": r.payload or {}} for r in rows]
    plan = compile_replay_plan(events, overrides or {})

    shadow = requires_confirmation(skill.skeleton) and not confirm_side_effect
    if shadow:
        run = ReplayRun(skill_id=skill_id, mode="shadow", status="shadow",
                        plan=plan, executed=None, assertion_results=None)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    async with _launch() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(plan["url"])
        result = await execute_plan(page, plan)
        await browser.close()

    assertions = [{"kind": a.kind, "payload": a.payload} for a in
                  db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).all()]
    results = evaluate_assertions(assertions, result["observed"])
    any_ok_step = any(s.get("ok") for s in result["executed"])
    if not any_ok_step:
        status = "error"
    elif all(r["passed"] for r in results):
        status = "pass"
    else:
        status = "fail"

    run = ReplayRun(skill_id=skill_id, mode="execute", status=status, plan=plan,
                    executed=result["executed"], assertion_results=results)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
```

`server/app/api/replay.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReplayRun, Skill
from app.replay.runner import run_replay

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ReplayRequest(BaseModel):
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/skills/{skill_id}/replay")
async def replay(skill_id: int, body: ReplayRequest, db: Session = Depends(get_db)) -> dict:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    run = await run_replay(db, skill_id, body.overrides, body.confirm_side_effect)
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path}


@router.get("/replay-runs/{run_id}")
async def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path}
```

main.py 挂载 replay router。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 71）

- [ ] **Step 5: Commit**

```bash
git add server/ && git commit -m "feat: 回放编排端点（C1 影子门控 + 断言判定 pass/fail/error）"
```

---

### Task 4: FAIL 归因（截图 + LLM，判定仍确定性）

**Files:**
- Modify: `server/app/replay/runner.py`（FAIL/ERROR 时截图 + 归因）
- Test: `server/tests/test_replay_failure.py`

**Interfaces:**
- Consumes: T1 Gateway `complete`（purpose=`replay_failure_attribution`）、T3 run_replay。
- Produces: status ∈ {fail, error} 时——截图存 `server/artifacts/replay-{run_id}.png`（`artifact_path` 记录），归因 prompt（失败的 steps + 失败断言 + 页面 title）→ `complete()` → 结果存 `attribution`；pass/shadow 不触发。截图目录加 .gitignore（`artifacts/` 已在根 .gitignore）。

- [ ] **Step 1: 写失败测试**

`server/tests/test_replay_failure.py`：

```python
import json

import app.replay.runner as rm
from tests.test_replay_api import _seed_skill


async def test_fail_triggers_attribution(client, monkeypatch, tmp_path):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 500, "body": "err"}]}

    class FakePage:
        async def goto(self, url): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def screenshot(self, path): open(path, "w").write("png")
        async def title(self): return "测试页"
    class FakeBrowser:
        async def new_page(self): return FakePage()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())
    monkeypatch.setattr(rm, "ARTIFACT_DIR", str(tmp_path))

    captured = {}

    def fake_complete(db, purpose, prompt):
        captured["purpose"] = purpose
        captured["prompt"] = prompt
        class R: text = "接口 500，保存服务异常"
        return R()
    monkeypatch.setattr(rm, "complete", fake_complete)

    resp = await client.post(f"/api/v1/skills/{skill_id}/replay",
                             json={"overrides": {}, "confirm_side_effect": True})
    body = resp.json()
    assert body["status"] == "fail"
    assert "500" in body["attribution"] or "异常" in body["attribution"]
    assert captured["purpose"] == "replay_failure_attribution"
    assert body["artifact_path"].endswith(".png")


async def test_pass_no_attribution(client, monkeypatch, tmp_path):
    skill_id = await _seed_skill(client, monkeypatch)

    async def fake_execute_plan(page, plan, **kw):
        return {"executed": [{"kind": "click", "label": "保存", "ok": True}],
                "observed": [{"url": "http://t/a/9/save", "status": 200,
                              "body": '{"code":200}'}]}

    class FakePage:
        async def goto(self, url): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def screenshot(self, path): open(path, "w").write("png")
        async def title(self): return "测试页"
    class FakeBrowser:
        async def new_page(self): return FakePage()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "execute_plan", fake_execute_plan)
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())
    monkeypatch.setattr(rm, "ARTIFACT_DIR", str(tmp_path))

    def fail_complete(*a, **k):
        raise AssertionError("pass must not call LLM")
    monkeypatch.setattr(rm, "complete", fail_complete)

    body = (await client.post(f"/api/v1/skills/{skill_id}/replay",
                              json={"overrides": {}, "confirm_side_effect": True})).json()
    assert body["status"] == "pass" and body["attribution"] is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_replay_failure.py -v` → FAIL

- [ ] **Step 3: 实现（runner.py 改造）**

模块顶部：`ARTIFACT_DIR = os.environ.get("REPLAY_ARTIFACT_DIR", str(Path(__file__).resolve().parents[2] / "artifacts"))`（import os/pathlib.Path）。run_replay 的 execute 分支在关闭浏览器前：若 `status in ("fail", "error")` → `path = f"{ARTIFACT_DIR}/replay-{{临时序号}}.png"`（先 mkdir）→ `await page.screenshot(path=...)`、`title = await page.title()`；落库后（拿到 run.id）若归因需要 → 用失败 steps/断言结果/title 构造 prompt（中文，含"只输出一段中文归因，不超过 100 字"）→ `complete(db, "replay_failure_attribution", prompt)` → `run.attribution = r.text; run.artifact_path = path; db.commit(); db.refresh(run)`。截图文件名因 run.id 未定，先用时间戳：`f"replay-{int(time.time()*1000)}.png"`。

（以文件实际形态做等效最小改造；`complete` 从 `app.llm.gateway` import 到模块顶部以便 monkeypatch。）

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 73）

- [ ] **Step 5: Commit**

```bash
git add server/ && git commit -m "feat: 回放失败截图与 LLM 归因（判定仍确定性）"
```

---

### Task 5: njmind 真实回放 E2E（演示 3 预演）

**Files:**
- Create: `demo/sprint4/README.md`、`demo/sprint4/replay-result.txt`

**Interfaces:**
- Consumes: 全部前序；用户提供的 njmind 可重置测试表单页 URL。
- Produces: Sprint 4 验收：换参数回放 PASS + 破坏断言判 FAIL（spec §7 Sprint 4 验收标准）。

- [ ] **Step 1: 启动**

```bash
cd server && uv run uvicorn app.main:app --port 8710   # 加载 .env 真实 LLM
```

- [ ] **Step 2: 用户准备（人工）**

给 SkillLens 提供一个**可重置/可重复保存**的 njmind 测试表单页 URL（设计器页即可，保存可重复执行）。告知操作者回放会真实点击"保存"。

- [ ] **Step 3: 首次影子模式（控制器执行）**

```bash
curl -s -X POST http://127.0.0.1:8710/api/v1/skills/1/replay \
  -H "Content-Type: application/json" -d '{"overrides": {}, "confirm_side_effect": false}'
# 预期 mode=shadow：不执行，返回编译好的计划（steps 含 click/input 及 label）
```

- [ ] **Step 4: 确认后执行模式（控制器执行，用户在旁观察 njmind）**

```bash
curl -s -X POST http://127.0.0.1:8710/api/v1/skills/1/replay \
  -H "Content-Type: application/json" \
  -d '{"overrides": {"请输入": "replay-e2e-001"}, "confirm_side_effect": true}'
# 预期：Playwright 打开 chromium → 语义定位执行 → status=pass
# 断言验证：saveFormConfig/saveTableConfig 均 200 + code=200
```

- [ ] **Step 5: FAIL 路径构造（控制器执行）**

改用不存在的 override 或临时改断言 expect_status（直接 SQL 把一条断言 expect_status 改 500）→ 重跑 → status=fail + attribution 生成 + 截图存在。验证后恢复断言。

- [ ] **Step 6: 验收记录**

1. shadow 不启浏览器（计划完整）；
2. execute 换参数 PASS（4 断言全过，观察含 saveFormConfig/saveTableConfig 200）；
3. FAIL 判定 + 截图 + LLM 归因（llm_call_log 有 replay_failure_attribution 记录）；
4. 定位策略记录（executed[].strategy 非 CSS）。

```bash
git add demo/sprint4/ && git commit -m "test: Sprint 4 njmind 真实回放验收（换参数 PASS + FAIL 归因）" && git push
```

- [ ] **Step 7: Sprint 回顾**

对照 spec §12（重点 #5 C1 零违规：shadow 未确认绝不启浏览器；#8 LLM 只归因不判定）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.5 定位策略（getByRole+label，不录 selector——locate.py 四级链+strategy 记录）→ T2；C1（destructive/影子——含 POST 未确认强制 shadow）→ T1 规则+T3 落地；换参数回放（变量从 Episode 注入）→ T1 overrides+T3；断言确定性优先+LLM 仅归因 → T2/T4；§7 Sprint 4 验收（换参数 PASS + 破坏断言 FAIL）→ T5 Step 4/5。未覆盖（Sprint 5+）：UI 快照 Before/After（本轮 E2E 强依据）、runner 独立进程+队列（Phase 3 形态，裁定：进程内模块）。
- **占位符**：T3 实现段有一处带删除说明的错误 import 示意（`_unused_placeholder` 行标注"删除此行，以文件实际形态做等效追加"）——已明确为转写指引而非待实现项；T4 的截图文件名时间戳方案已写明。
- **类型一致性**：`compile_replay_plan(events, overrides) -> {url, steps}` 与 T3 消费一致；`execute_plan(page, plan, timeout_ms=5000)` 签名在 T2 定义、T3/T4 的 fake 一致（`**kw` 兼容）；`evaluate_assertions(assertions, observed)` 的元素结构 `{kind, payload}` / `{url, status, body}` 在 T2 测试、T3 编排、T4 fake 中一致；`run_replay(db, skill_id, overrides, confirm_side_effect)` 与端点一致；ReplayRun 字段名与两个端点返回键一致。
- **已知取舍**：field_change 断言回放时跳过（无 before/after 语义，记 skipped）；观察 body 截 8KB；FAIL 截图文件名用时间戳（run.id 落库前未知）；playwright chromium 首次下载约 150MB（T1 装一次）。


