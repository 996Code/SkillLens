# Sprint 5 Change Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Expected Delta 生成（LLM+人工确认）→ Observed Delta（回放观测）→ 四分类报告（Expected/Missing/Unexpected/Drift），在 njmind 上真实构造触发 Missing 与 Unexpected。

**Architecture:** 新增 `app/change/` 包三模块（expected/observed/classify）+ `app/api/change.py` 路由 + 三张表。LLM 只做需求→结构化的生成（过确定性 verify，失败存 draft 带原因）；Observed 从既有 replay_run 的 executed/assertion_results 确定性提取；四分类纯匹配规则 + Drift 时序阈值比对。全部中间产物落库（C3）。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic（既有）；无新依赖。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md` §4.6（Change Intelligence Engine）、§5（expected_delta/observed_delta/delta_report 三表）、§7 Sprint 5 行；YAML schema 参考 `docs/references/ai_software_learning_change_intelligence_v3.md` §21-25。

## Global Constraints

- **C1 影子模式**：observe 端点透传 `confirm_side_effect` 给 `run_replay`；skill 含写方法且未确认 → shadow run，**不产生 observed_delta**（HTTP 409 报"shadow 未执行，无观测"）。
- **C3 全链路持久化**：expected_delta（draft/confirmed 两态）/observed_delta/delta_report 全落库；LLM 调用一律走 `complete(db, "expected_delta", prompt)`（llm_call_log 全量）。
- **LLM 边界**：结构化生成走 LLM；verify_delta 与四分类判定全确定性（纯函数，无 LLM）。verify 失败 → 存 draft（notes 记原因），不阻塞人工流程（人工可在 confirm 时修正 changes）。
- **人工确认（spec §4.6）**：expected_delta 必须经 `POST /expected-deltas/{id}/confirm` 才生效（status=confirmed）；confirm 允许人工修订 changes（MVP 的"人审"形态，也是真实构造 Unexpected 的入口）。
- **安全**：server/.env 不入库不打印；测试进程 LLM_API_KEY 预置空（conftest 已有）；任何代码/测试/文档不得含真实 key/网关域名/njmind 凭据。
- 测试基线：pytest 81（每任务完成后全量必须通过）；vitest 19 不动（本 Sprint 无插件改动）。
- 预期变更类型 MVP 限定三类：`ui_action`、`api_add`、`api_status`（state_signal 观测值未落 replay_run，无法匹配——记入 plan 已知取舍，Phase 2 扩）。

---

### Task 1: 三表模型 + 迁移

**Files:**
- Modify: `server/app/models.py`（文件末尾追加三个类）
- Create: `server/alembic/versions/<autogen>_change_intelligence.py`（autogenerate）
- Test: `server/tests/test_delta_models.py`

**Interfaces:**
- Consumes: 既有 `Base`/`utcnow()`（app/models.py 顶部）。
- Produces: `ExpectedDelta`、`ObservedDelta`、`DeltaReport` ORM 类；后续任务 import 用。

- [ ] **Step 1: 写失败测试**（`server/tests/test_delta_models.py`）

```python
from app.db import engine
from app.models import Base, ExpectedDelta, ObservedDelta, DeltaReport


def test_change_tables_created():
    Base.metadata.create_all(engine)
    import sqlalchemy as sa
    insp = sa.inspect(engine)
    for t in ("expected_delta", "observed_delta", "delta_report"):
        assert insp.has_table(t), f"缺表 {t}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_delta_models.py -v`
Expected: FAIL（ImportError: cannot import name 'ExpectedDelta'）

- [ ] **Step 3: models.py 末尾追加**（注意 raw_event 假 NOT NULL 迁移噪音——autogenerate 后检查 diff 只含三张新表，多余 alter 用 `--autogenerate` 后手删）

```python
class ExpectedDelta(Base):
    __tablename__ = "expected_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column()
    requirement_text: Mapped[str] = mapped_column(Text)
    feature: Mapped[str] = mapped_column(String(100), default="")
    changes: Mapped[list] = mapped_column(JSON)          # [{"type","value"}]
    status: Mapped[str] = mapped_column(String(20))      # draft|confirmed
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ObservedDelta(Base):
    __tablename__ = "observed_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expected_delta_id: Mapped[int] = mapped_column(index=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    replay_run_id: Mapped[int] = mapped_column()
    items: Mapped[list] = mapped_column(JSON)            # 同 changes 结构
    duration_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DeltaReport(Base):
    __tablename__ = "delta_report"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expected_delta_id: Mapped[int] = mapped_column(index=True)
    observed_delta_id: Mapped[int] = mapped_column(index=True)
    expected: Mapped[list] = mapped_column(JSON)
    missing: Mapped[list] = mapped_column(JSON)
    unexpected: Mapped[list] = mapped_column(JSON)
    drift: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

- [ ] **Step 4: 生成迁移并检查**

```bash
cd server && uv run alembic revision --autogenerate -m "change_intelligence" && uv run alembic upgrade head
```
检查生成文件：只应包含三张 create_table；若出现 raw_event 的 alter（假 NOT NULL 噪音，第 4 次出现）——整段删除，只留新表。

- [ ] **Step 5: 测试通过 + 全量回归 + 提交**

Run: `uv run pytest` → 82 passed
```bash
git add server/app/models.py server/alembic/versions/ server/tests/test_delta_models.py
git commit -m "feat(change): expected_delta/observed_delta/delta_report 三表模型与迁移"
```

---

### Task 2: Expected Delta 生成（LLM 结构化 + verify + confirm）

**Files:**
- Create: `server/app/change/__init__.py`（空）
- Create: `server/app/change/expected.py`
- Modify: `server/app/api/change.py`（本任务创建骨架：生成/确认/查询三端点）
- Modify: `server/app/main.py:20` 后追加 `app.include_router(change.router, prefix=API_PREFIX)`
- Test: `server/tests/test_expected_delta.py`

**Interfaces:**
- Consumes: `complete(db, purpose, prompt) -> LlmResult`（app/llm/gateway.py）；`ExpectedDelta`（Task 1）。
- Produces:
  - `build_prompt(requirement_text: str) -> str`
  - `parse_delta(text: str) -> list[dict] | None`（容忍 ```json 包裹，复用 skill.py 的正则思路）
  - `verify_delta(changes: list[dict]) -> tuple[bool, str]`（type ∈ {ui_action,api_add,api_status}；value 非空 str；≤20 条）
  - `generate_expected_delta(db, requirement_text, requirement_id) -> ExpectedDelta`（status=draft；verify 失败时 changes 存 LLM 原样、notes 记原因）
  - API：`POST /expected-deltas`（body: requirement_id, requirement_text）→ 201 {id, status, changes, notes}；`POST /expected-deltas/{id}/confirm`（body: reviewed_by, changes 可选——提供则覆盖，人工修订入口）→ status=confirmed；`GET /expected-deltas/{id}`。

- [ ] **Step 1: 写失败测试**（`server/tests/test_expected_delta.py`）

```python
import json


def _post(client, text, rid="req-1"):
    return client.post("/api/v1/expected-deltas",
                       json={"requirement_id": rid, "requirement_text": text})


def test_generate_draft_and_confirm(client, monkeypatch):
    fake = json.dumps({"feature": "RenameFormButton",
                       "changes": [{"type": "ui_action", "value": "保存按钮改名为提交"}]})
    monkeypatch.setenv("LLM_FAKE_RESPONSE", fake)
    r = _post(client, "把保存按钮改名为提交")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and len(body["changes"]) == 1

    rc = client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                     json={"reviewed_by": "tester"})
    assert rc.json()["status"] == "confirmed"
    # 再次 confirm 返回 409
    assert client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                       json={"reviewed_by": "x"}).status_code == 409


def test_confirm_can_revise_changes(client, monkeypatch):
    """人工修订入口：confirm 时覆盖 changes——真实构造 Unexpected 的基础。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": [{"type": "ui_action", "value": "A"}]}))
    body = _post(client, "需求").json()
    revised = [{"type": "ui_action", "value": "A"},
               {"type": "api_add", "value": "/codeBack/formConfig/saveFormConfig"}]
    rc = client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                     json={"reviewed_by": "t", "changes": revised})
    assert rc.json()["status"] == "confirmed" and len(rc.json()["changes"]) == 2


def test_generate_verify_failure_stores_draft_with_reason(client, monkeypatch):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "垃圾输出非 JSON")
    body = _post(client, "需求").json()
    assert body["status"] == "draft" and "无法解析" in body["notes"]
```

- [ ] **Step 2: 跑测试确认失败**（ImportError / 404）

Run: `cd server && uv run pytest tests/test_expected_delta.py -v`

- [ ] **Step 3: 实现 `app/change/expected.py`**

```python
import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import ExpectedDelta

ALLOWED_TYPES = {"ui_action", "api_add", "api_status"}
MAX_CHANGES = 20


def build_prompt(requirement_text: str) -> str:
    lines = [
        "你在把一条软件需求结构化为预期变更清单（Expected Delta）。",
        "类型限定三种：ui_action（UI 按钮/标签/文案变化，value 写成如'保存按钮改名为提交'），"
        "api_add（新增或调用的 API，value 写成模板路径如 /codeBack/formConfig/saveFormConfig），"
        "api_status（API 响应状态或顶层 code 的预期，value 写成如 /x/y -> 200）。",
        f"需求：{requirement_text}",
        '只返回 JSON，不要任何其他文字: {"feature": "PascalCase英文特征名", '
        '"changes": [{"type": "...", "value": "..."}]}',
    ]
    return "\n".join(lines)


def parse_delta(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def verify_delta(changes: list) -> tuple[bool, str]:
    if not isinstance(changes, list) or not changes:
        return False, "changes 必须是非空数组"
    if len(changes) > MAX_CHANGES:
        return False, f"changes 超过 {MAX_CHANGES} 条"
    for c in changes:
        if c.get("type") not in ALLOWED_TYPES:
            return False, f"未知类型 {c.get('type')}"
        if not str(c.get("value") or "").strip():
            return False, "value 不能为空"
    return True, ""


def generate_expected_delta(db: Session, requirement_text: str,
                            requirement_id: str) -> ExpectedDelta:
    result = complete(db, "expected_delta", build_prompt(requirement_text))
    proposal = parse_delta(result.text)
    changes, feature, notes = [], "", ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        feature = str(proposal.get("feature") or "")[:100]
        changes = proposal.get("changes") or []
        ok, why = verify_delta(changes)
        if not ok:
            notes = why  # changes 保留原样供人工修订
    row = ExpectedDelta(requirement_id=requirement_id, requirement_text=requirement_text,
                        feature=feature, changes=changes, status="draft", notes=notes)
    db.add(row); db.commit(); db.refresh(row)
    return row
```

- [ ] **Step 4: 实现 `app/api/change.py` 骨架**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.change.expected import generate_expected_delta, verify_delta
from app.db import SessionLocal
from app.models import ExpectedDelta

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class CreateDeltaRequest(BaseModel):
    requirement_id: str
    requirement_text: str


class ConfirmRequest(BaseModel):
    reviewed_by: str
    changes: list[dict] | None = None


@router.post("/expected-deltas", status_code=201)
async def create_expected(body: CreateDeltaRequest, db: Session = Depends(get_db)) -> dict:
    row = generate_expected_delta(db, body.requirement_text, body.requirement_id)
    return {"id": row.id, "status": row.status, "changes": row.changes, "notes": row.notes}


@router.post("/expected-deltas/{delta_id}/confirm")
async def confirm_expected(delta_id: int, body: ConfirmRequest,
                           db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    if row.status == "confirmed":
        raise HTTPException(409, "已确认过，不可重复确认")
    if body.changes is not None:
        ok, why = verify_delta(body.changes)
        if not ok:
            raise HTTPException(422, why)
        row.changes = body.changes
    row.status = "confirmed"
    row.reviewed_by = body.reviewed_by
    db.commit(); db.refresh(row)
    return {"id": row.id, "status": row.status, "changes": row.changes}


@router.get("/expected-deltas/{delta_id}")
async def get_expected(delta_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(ExpectedDelta, delta_id)
    if not row:
        raise HTTPException(404, "expected delta not found")
    return {"id": row.id, "requirement_id": row.requirement_id,
            "feature": row.feature, "changes": row.changes, "status": row.status,
            "reviewed_by": row.reviewed_by, "notes": row.notes}
```

main.py 注册：`from app.api import change` + `app.include_router(change.router, prefix=API_PREFIX)`。

- [ ] **Step 5: 测试通过 + 全量回归 + 提交**

Run: `uv run pytest` → 85 passed
```bash
git add server/app/change/ server/app/api/change.py server/app/main.py server/tests/test_expected_delta.py
git commit -m "feat(change): Expected Delta 生成（LLM 结构化+确定性 verify+人工 confirm 修订）"
```

---

### Task 3: Observed Delta（回放观测提取，纯确定性）

**Files:**
- Create: `server/app/change/observed.py`
- Modify: `server/app/api/change.py`（追加 observe 端点）
- Test: `server/tests/test_observed_delta.py`

**Interfaces:**
- Consumes: `run_replay(db, skill_id, overrides, confirm_side_effect) -> ReplayRun`（app/replay/runner.py，既有）；`path_matches(url, template)`（app/replay/assert_eval.py，既有）；`ObservedDelta`（Task 1）。
- Produces:
  - `extract_observed(run: ReplayRun) -> list[dict]`（纯函数：从 replay_run 的 executed/assertion_results 提取观测项，格式与 changes 同构 `[{"type","value"}]`）
  - `run_observe(db, expected_delta_id, skill_id, overrides, confirm_side_effect) -> ObservedDelta`（编排：校验 expected 已 confirmed → run_replay → shadow 短路 409 → 提取落库）
  - API：`POST /expected-deltas/{id}/observe`（body: skill_id, overrides?, confirm_side_effect）→ 201 {id, items, replay_run_id, replay_status}；expected 未 confirmed → 409；shadow → 409 {"detail": "shadow run 未执行，无观测"}。
  - 提取规则（确定性）：
    - executed 里每个 ok=true 的 click 步 → `{"type":"ui_action","value": f"点击 {label}"}`
    - executed 里每个 ok=true 的 input 步 → `{"type":"ui_action","value": f"输入 {name}={value}"}`
    - observed 网络去重后的每个 api 模板 → `{"type":"api_add","value": 模板}`（从 run.plan 无法取 observed——**从 assertion_results 取**：payload.api_template 即调用的 API）
    - assertion_results 里 api_status 类 → `{"type":"api_status","value": f"{api_template} -> {observed_status}"}`（仅 observed_status 非 None 的）
    - duration_ms = replay_run.created_at 与前一 run 无从比——MVP 用 run 内首尾时间差不可得，**duration_ms 存 0**，真实时序 Drift 检测用 replay 断言耗时（Task 4 说明）

- [ ] **Step 1: 写失败测试**（`server/tests/test_observed_delta.py`）

```python
import json

from tests.test_replay_api import _seed_skill
import app.replay.runner as rm


def _fake_plan_result():
    return {"executed": [
                {"kind": "input", "name": "请输入", "value": "v1", "ok": True},
                {"kind": "click", "label": "保存", "ok": True}],
            "observed": []}


def _mk_fake(execute_result):
    async def fake_execute_plan(page, plan, **kw):
        return execute_result
    return fake_execute_plan


async def _prepare_confirmed_delta(client, monkeypatch, changes):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": changes}))
    body = (await client.post("/api/v1/expected-deltas",
                              json={"requirement_id": "r1",
                                    "requirement_text": "需求"})).json()
    await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                      json={"reviewed_by": "t"})
    return body["id"]


async def test_observe_extracts_and_lands(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    delta_id = await _prepare_confirmed_delta(client, monkeypatch, [
        {"type": "ui_action", "value": "点击 保存"}])

    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, s, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()

    result = _fake_plan_result()
    result["observed"] = [
        {"url": "http://t/a/1/save", "status": 200, "body": '{"code":200}'}]
    monkeypatch.setattr(rm, "execute_plan", _mk_fake(result))
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())

    r = await client.post(f"/api/v1/expected-deltas/{delta_id}/observe",
                          json={"skill_id": skill_id, "confirm_side_effect": True})
    assert r.status_code == 201
    body = r.json()
    assert {"type": "ui_action", "value": "点击 保存"} in body["items"]
    assert any(i["type"] == "api_add" and "save" in i["value"] for i in body["items"])
    assert any(i["type"] == "api_status" and "-> 200" in i["value"]
               for i in body["items"])


async def test_observe_rejects_draft(client, monkeypatch):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": [{"type": "ui_action", "value": "A"}]}))
    body = (await client.post("/api/v1/expected-deltas",
                              json={"requirement_id": "r1",
                                    "requirement_text": "需求"})).json()
    r = await client.post(f"/api/v1/expected-deltas/{body['id']}/observe",
                          json={"skill_id": 1, "confirm_side_effect": True})
    assert r.status_code == 409
```

注：`_seed_skill` 含 POST 骨架 → requires_confirmation=True；confirm_side_effect=True 才能 execute。shadow 路径（409 无观测）由 fake `_launch` 未设置时自然覆盖——不单独写用例，端到端在 Task 5 真实验证。

- [ ] **Step 2: 跑测试确认失败**（observe 端点 404）

Run: `cd server && uv run pytest tests/test_observed_delta.py -v`

- [ ] **Step 3: 实现 `app/change/observed.py`**

```python
from sqlalchemy.orm import Session

from app.models import ExpectedDelta, ObservedDelta, ReplayRun, Skill
from app.replay.runner import run_replay


def extract_observed(run: ReplayRun) -> list[dict]:
    items: list[dict] = []
    for step in (run.executed or []):
        if not step.get("ok"):
            continue
        if step.get("kind") == "click":
            items.append({"type": "ui_action", "value": f"点击 {step.get('label', '')}"})
        elif step.get("kind") == "input":
            items.append({"type": "ui_action",
                          "value": f"输入 {step.get('name', '')}={step.get('value', '')}"})
    seen_api: set[str] = set()
    for a in (run.assertion_results or []):
        tpl = (a.get("payload") or {}).get("api_template", "")
        if not tpl or tpl in seen_api:
            continue
        seen_api.add(tpl)
        items.append({"type": "api_add", "value": tpl})
        if a.get("observed_status") is not None and a.get("payload", {}).get("expect_status") is not None:
            items.append({"type": "api_status",
                          "value": f"{tpl} -> {a['observed_status']}"})
    return items


async def run_observe(db: Session, expected_delta_id: int, skill_id: int,
                      overrides: dict[str, str], confirm_side_effect: bool) -> ObservedDelta:
    delta = db.get(ExpectedDelta, expected_delta_id)
    if not delta or delta.status != "confirmed":
        raise ValueError("expected delta 未确认，不能观测")
    if not db.get(Skill, skill_id):
        raise LookupError("skill not found")
    run = await run_replay(db, skill_id, overrides or {}, confirm_side_effect)
    if run.mode == "shadow":
        raise PermissionError("shadow run 未执行，无观测")
    items = extract_observed(run)
    row = ObservedDelta(expected_delta_id=expected_delta_id, skill_id=skill_id,
                        replay_run_id=run.id, items=items, duration_ms=0)
    db.add(row); db.commit(); db.refresh(row)
    return row
```

- [ ] **Step 4: `app/api/change.py` 追加端点**

```python
class ObserveRequest(BaseModel):
    skill_id: int
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/expected-deltas/{delta_id}/observe", status_code=201)
async def observe(delta_id: int, body: ObserveRequest,
                  db: Session = Depends(get_db)) -> dict:
    from app.change.observed import run_observe
    try:
        row = await run_observe(db, delta_id, body.skill_id,
                                body.overrides, body.confirm_side_effect)
    except ValueError as e:
        raise HTTPException(409, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    return {"id": row.id, "items": row.items, "replay_run_id": row.replay_run_id}
```

- [ ] **Step 5: 测试通过 + 全量回归 + 提交**

Run: `uv run pytest` → 87 passed
```bash
git add server/app/change/observed.py server/app/api/change.py server/tests/test_observed_delta.py
git commit -m "feat(change): Observed Delta 提取与 observe 端点（C1 shadow 409 短路）"
```

---

### Task 4: 四分类报告（纯函数 + 端点）

**Files:**
- Create: `server/app/change/classify.py`
- Modify: `server/app/api/change.py`（追加 report 端点）
- Test: `server/tests/test_delta_classify.py`

**Interfaces:**
- Consumes: `ExpectedDelta.changes` / `ObservedDelta.items`（同构 `[{"type","value"}]`）。
- Produces:
  - `classify_delta(expected_changes: list[dict], observed_items: list[dict], baseline_ms: int = 0, observed_ms: int = 0) -> dict`（纯函数，返回 `{"expected": [...], "missing": [...], "unexpected": [...], "drift": [...]}`，元素为变更项 + 归类信息）
  - API：`POST /expected-deltas/{id}/report`（body: observed_delta_id）→ 201 报告（落 delta_report 表）
  - 匹配规则（确定性，逐条）：
    - expected 项在 observed 中找到匹配（type 相同 + value 精确相等，或 value 前缀匹配见下）→ **expected**
    - expected 项无匹配 → **missing**
    - observed 项未被任何 expected 匹配 → **unexpected**
    - **Drift（MVP 时序）**：`api_status` 类 expected 项若 observed 有同 api 但状态不同的条目 → drift 项 `{"type":"api_status","value": f"{api}: {期待} -> {实际}"}`（同时该 expected 项归 missing，drift 单列——四分类里 Drift 表示"表面在但行为变"）
    - value 匹配辅助：`api_status` 的 value 形如 `"{api} -> {code}"`，匹配时按 api 前缀对齐（expected `/x -> 200` vs observed `/x -> 500`：api 相同 → 不算 expected 也不算 missing，进 drift）
  - ui_action 的 value 是自然语言（LLM 生成）——MVP 用**子串包含**匹配（expected "点击 保存" vs observed "点击 保存" 精确相等即中；若 expected 是"保存按钮改名为提交"这类自然语言与 observed "点击 保存" 不匹配 → missing。这是 LLM 值与观测值的现实鸿沟，**人工 confirm 修订是弥合入口**，Task 5 真实演示会走这条路）。

- [ ] **Step 1: 写失败测试**（`server/tests/test_delta_classify.py`）

```python
from app.change.classify import classify_delta


def test_all_four_categories():
    expected_changes = [
        {"type": "ui_action", "value": "点击 保存"},          # 会命中
        {"type": "api_add", "value": "/a/save"},              # 会命中
        {"type": "ui_action", "value": "新增复制按钮"},        # 不命中 → missing
        {"type": "api_status", "value": "/a/save -> 200"},    # api 在但 500 → drift
    ]
    observed_items = [
        {"type": "ui_action", "value": "点击 保存"},
        {"type": "api_add", "value": "/a/save"},
        {"type": "api_status", "value": "/a/save -> 500"},
        {"type": "api_add", "value": "/a/export"},            # 无对应预期 → unexpected
    ]
    r = classify_delta(expected_changes, observed_items)
    assert {"type": "ui_action", "value": "点击 保存"} in r["expected"]
    assert {"type": "api_add", "value": "/a/save"} in r["expected"]
    assert {"type": "ui_action", "value": "新增复制按钮"} in r["missing"]
    assert {"type": "api_add", "value": "/a/export"} in r["unexpected"]
    assert any("/a/save" in d["value"] and "200" in d["value"] and "500" in d["value"]
               for d in r["drift"])
    # drift 的 api_status expected 项不再计入 expected/missing
    assert not any("-> 200" in e["value"] for e in r["expected"])
    assert not any("-> 200" in m["value"] for m in r["missing"])


def test_empty_edges():
    r = classify_delta([], [{"type": "api_add", "value": "/x"}])
    assert r["unexpected"] and not r["expected"] and not r["missing"]
    r2 = classify_delta([{"type": "api_add", "value": "/x"}], [])
    assert r2["missing"] and not r2["unexpected"]
```

- [ ] **Step 2: 跑测试确认失败**（ModuleNotFoundError）

Run: `cd server && uv run pytest tests/test_delta_classify.py -v`

- [ ] **Step 3: 实现 `app/change/classify.py`**

```python
def _api_of(value: str) -> tuple[str, str] | None:
    """"/a -> 200" 拆 (api, code)；非该形态返回 None。"""
    if " -> " not in value:
        return None
    api, _, code = value.partition(" -> ")
    return api.strip(), code.strip()


def classify_delta(expected_changes: list[dict], observed_items: list[dict],
                   baseline_ms: int = 0, observed_ms: int = 0) -> dict:
    expected: list[dict] = []
    missing: list[dict] = []
    unexpected: list[dict] = []
    drift: list[dict] = []

    obs_by_type: dict[str, list[dict]] = {}
    for o in observed_items:
        obs_by_type.setdefault(o["type"], []).append(o)

    matched_obs_ids: set[int] = set()  # 用 (type,value) 做身份
    obs_keys = [(o["type"], o["value"]) for o in observed_items]

    for e in expected_changes:
        pair = _api_of(e["value"])
        hit = None
        if e["type"] == "api_status" and pair:
            api, want_code = pair
            for o in obs_by_type.get("api_status", []):
                opair = _api_of(o["value"])
                if opair and opair[0] == api:
                    if opair[1] == want_code:
                        hit = o
                    else:
                        drift.append({"type": "api_status",
                                      "value": f"{api}: {want_code} -> {opair[1]}"})
                    break
        else:
            for o in obs_by_type.get(e["type"], []):
                if o["value"] == e["value"] or (
                        e["type"] == "ui_action" and (
                            e["value"] in o["value"] or o["value"] in e["value"])):
                    hit = o
                    break
        if hit is not None:
            expected.append(e)
            matched_obs_ids.add(obs_keys.index((hit["type"], hit["value"])))
        elif not (e["type"] == "api_status" and pair and any(
                d["value"].startswith(_api_of(e["value"])[0] + ":") for d in drift)):
            missing.append(e)

    for i, o in enumerate(observed_items):
        if i not in matched_obs_ids:
            # drift 项的 observed 对应条目不算 unexpected
            pair = _api_of(o["value"])
            if pair and any(d["value"].startswith(pair[0] + ":") for d in drift):
                continue
            unexpected.append(o)

    if baseline_ms and observed_ms and observed_ms > baseline_ms * 3:
        drift.append({"type": "timing", "value": f"耗时 {baseline_ms}ms -> {observed_ms}ms"})
    return {"expected": expected, "missing": missing,
            "unexpected": unexpected, "drift": drift}
```

（MVP duration_ms=0，时序 drift 分支留接口不触发——Task 3 已注明。）

- [ ] **Step 4: `app/api/change.py` 追加 report 端点**

```python
class ReportRequest(BaseModel):
    observed_delta_id: int


@router.post("/expected-deltas/{delta_id}/report", status_code=201)
async def report(delta_id: int, body: ReportRequest,
                 db: Session = Depends(get_db)) -> dict:
    from app.change.classify import classify_delta
    from app.models import DeltaReport, ObservedDelta
    delta = db.get(ExpectedDelta, delta_id)
    obs = db.get(ObservedDelta, body.observed_delta_id)
    if not delta or not obs:
        raise HTTPException(404, "expected/observed delta not found")
    if obs.expected_delta_id != delta_id:
        raise HTTPException(409, "observed delta 不属于该 expected delta")
    r = classify_delta(delta.changes, obs.items)
    row = DeltaReport(expected_delta_id=delta_id, observed_delta_id=obs.id,
                      expected=r["expected"], missing=r["missing"],
                      unexpected=r["unexpected"], drift=r["drift"])
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "expected_delta_id": delta_id,
            "observed_delta_id": obs.id, **r}
```

- [ ] **Step 5: 测试通过 + 全量回归 + 提交**

Run: `uv run pytest` → 89 passed
```bash
git add server/app/change/classify.py server/app/api/change.py server/tests/test_delta_classify.py
git commit -m "feat(change): 四分类报告（Expected/Missing/Unexpected/Drift 纯函数匹配）"
```

---

### Task 5: njmind 真实 E2E——演示 3（改一个需求 → 输出报告）

**Files:**
- Create: `demo/sprint5/README.md`、`demo/sprint5/delta-report.txt`

**Interfaces:**
- Consumes: 全部前序；Skill #2（learned，4 断言）；`scripts/njmind_login.py`（登录态）；server 以 `REPLAY_STORAGE_STATE=/tmp/njmind-state-auto.json` 运行。
- Produces: spec §7 Sprint 5 验收——**四分类中 Missing 和 Unexpected 至少各能被真实构造触发一次**。

- [ ] **Step 1: 启动**（控制器执行）

```bash
cd server && uv run python ../scripts/njmind_login.py /tmp/njmind-state-auto.json
kill $(lsof -ti :8710); REPLAY_STORAGE_STATE=/tmp/njmind-state-auto.json \
  nohup uv run uvicorn app.main:app --port 8710 > /tmp/skilllens-server-8710.log 2>&1 &
```

- [ ] **Step 2: 需求 → Expected Delta（真实 LLM）**

需求文本（贴近真实场景）：`表单设计器保存后应调用表格配置保存接口，且接口返回成功状态`。
```bash
curl -s -X POST http://127.0.0.1:8710/api/v1/expected-deltas \
  -H "Content-Type: application/json" \
  -d '{"requirement_id": "demo3-req-1", "requirement_text": "表单设计器保存后应调用表格配置保存接口，且接口返回成功状态"}'
```
检查 LLM 产物（llm_call_log purpose=expected_delta）；**人工修订**：confirm 时把 changes 修订为观测可匹配的精确形态（人工审的弥合入口）：
```json
{"reviewed_by": "operator",
 "changes": [
   {"type": "ui_action", "value": "点击 保存"},
   {"type": "api_add", "value": "/codeBack/tableConfig/saveTableConfig"},
   {"type": "api_status", "value": "/codeBack/tableConfig/saveTableConfig -> 200"},
   {"type": "ui_action", "value": "新增复制按钮"}
 ]}
```
（最后一条故意保留——真实系统没有该按钮/动作，将构造 **Missing**。）
```bash
curl -s -X POST http://127.0.0.1:8710/api/v1/expected-deltas/1/confirm -H "Content-Type: application/json" -d '{...上修订...}'
```

- [ ] **Step 3: observe + report（真实回放）**

```bash
curl -s -X POST http://127.0.0.1:8710/api/v1/expected-deltas/1/observe \
  -H "Content-Type: application/json" \
  -d '{"skill_id": 2, "overrides": {"请输入": "delta-demo-001"}, "confirm_side_effect": true}'
curl -s -X POST http://127.0.0.1:8710/api/v1/expected-deltas/1/report \
  -H "Content-Type: application/json" -d '{"observed_delta_id": 1}'
```
预期分类：
- expected：点击 保存 / api_add saveTableConfig / api_status -> 200
- **missing：新增复制按钮**（验收点 1 ✓）
- unexpected：观测到但预期外的项（如 getTableConfigByFormConfigId、input 请输入——**验收点 2 ✓**）
- drift：空（无时序数据）

- [ ] **Step 4: shadow 路径核验（C1）**

confirm_side_effect=false 重跑 observe → 409 "shadow run 未执行，无观测"，且 DB 无新 observed_delta。确认后可跳过（若 Step 3 已证 execute 路径，此处只 curl 验证 409 文案）。

- [ ] **Step 5: 验收记录**

demo/sprint5/README.md 记录：需求文本、LLM 原始产物 vs 人工修订 diff、四分类结果（Missing/Unexpected 真实触发证据）、llm_call_log 摘要、C1 核验。replay-result 同步导出到 delta-report.txt。

```bash
git add demo/sprint5/ && git commit -m "test: Sprint 5 演示3验收（改需求→四分类报告，Missing/Unexpected 真实触发）"
```

- [ ] **Step 6: Sprint 回顾**

对照 spec §12（#5 C1 零违规：shadow 409 短路；#8 LLM 只生成不判定：verify/classify 纯函数）。E2E 修复轮按 project-lessons.md #12 预留（LLM 产物形态不可控时，靠 confirm 修订弥合——这是设计内路径不是 fallback）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.6 Expected Delta（LLM 结构化+人工确认）→ T2；Observed Delta（重放+提取）→ T3；四分类 → T4（Drift MVP 时序接口留空不触发，spec 允许"只做时序对比"且 duration 数据源未落，记已知取舍）；§5 三表 → T1；§7 Sprint 5 验收（Missing/Unexpected 真实构造）→ T5 Step 3（missing=虚构"新增复制按钮"，unexpected=观测到的输入/API 项不在预期）。演示 3 → T5。
- **占位符**：无 TBD/TODO；T3 的 duration_ms=0 与 T4 的时序分支为显式已知取舍（含理由），非未完成项。
- **类型一致性**：changes/items 同构 `[{"type","value"}]` 在 T2/T3/T4 一致；`classify_delta(expected_changes, observed_items)` 签名与 T4 端点调用一致；`run_observe(db, expected_delta_id, skill_id, overrides, confirm_side_effect)` 与端点一致；`extract_observed(run: ReplayRun)` 与 run_replay 返回一致；端点路径前缀 /api/v1（main.py API_PREFIX）全一致。
- **已知取舍**：state_signal 不在观测提取（replay_run 未落响应体字段值，Phase 2 扩 assert_eval 落 observed_fields）；ui_action 自然语言匹配靠 confirm 修订弥合；duration_ms=0（时序 Drift Phase 2）。
- **测试计数**：T1 +1（82）、T2 +3（85）、T3 +2（87）、T4 +2（89）、T5 无新测试（E2E）。
