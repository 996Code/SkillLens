# Sprint 0 实施计划：仓库骨架 + 插件采集 POC

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭起 server + extension 双端骨架，在 njmind 上用插件采集一次完整表单操作的 UI/Action/Network 原始事件，全部落入 `raw_event` 表。

**Architecture:** FastAPI + SQLAlchemy 2.0（SQLite/Alembic）作为 Local Agent；Chrome 插件（Manifest V3 + Vite/CRXJS）分三层：content script 采集动作与 UI、MAIN world 注入脚本包装 fetch/XHR 观察网络、IndexedDB 缓冲后批量上报。插件侧先做基础脱敏。

**Tech Stack:** Python 3.12 + uv、FastAPI、SQLAlchemy 2.0、Alembic、pytest + httpx；TypeScript、Vite + @crxjs/vite-plugin、vitest。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md`（§4.1、§4.2、§5、§6、§7 Sprint 0）

## Global Constraints（每个任务默认遵守）

- C3 全链路持久化：采集的原始事件必须落库，不允许只打印/只存内存。
- `raw_event` 表 append-only：只 INSERT，禁止 UPDATE/DELETE。
- 所有表带 `created_at`；事件带 `session_id + seq`，`(session_id, seq)` 唯一。
- 插件默认只上报到本地 Agent `http://127.0.0.1:8710`，URL 写在配置常量里。
- server 端每个任务完成时 pytest 全量通过才算完成。
- 提交信息用中文，格式 `feat|test|chore: 描述`。

## File Structure

```text
SkillLens/
├── extension/
│   ├── manifest.config.ts          # MV3 manifest（CRXJS）
│   ├── vite.config.ts
│   ├── package.json
│   ├── src/
│   │   ├── shared/
│   │   │   ├── types.ts            # RawEvent TS 类型（与 server Pydantic 对齐）
│   │   │   ├── describe-element.ts # 元素语义描述（纯函数）
│   │   │   └── redact.ts           # 脱敏（纯函数）
│   │   ├── content/
│   │   │   ├── capture.ts          # 动作/UI 采集入口
│   │   │   └── network-observer.ts # 接收 MAIN world 网络事件
│   │   ├── injected/
│   │   │   └── net-hook.ts         # MAIN world：包装 fetch/XHR
│   │   ├── background/
│   │   │   └── uploader.ts         # IndexedDB 缓冲 + 批量上报
│   │   └── store/
│   │       └── idb.ts              # IndexedDB 极简封装
├── server/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py                 # FastAPI 入口
│   │   ├── config.py               # 端口 8710、DB 路径等常量
│   │   ├── models.py               # SQLAlchemy models
│   │   ├── schemas.py              # Pydantic 事件 schema
│   │   └── api/
│   │       ├── health.py
│   │       └── events.py           # sessions + events 批量接口
│   └── tests/
│       ├── conftest.py
│       ├── test_health.py
│       ├── test_sessions.py
│       └── test_events.py
└── demo/                           # Sprint 0 演示记录（截图/SQL 查询结果）
```

---

### Task 1: server 骨架 + health 接口

**Files:**
- Create: `server/pyproject.toml`、`server/app/main.py`、`server/app/config.py`、`server/app/api/health.py`
- Test: `server/tests/conftest.py`、`server/tests/test_health.py`

**Interfaces:**
- Produces: FastAPI app 实例 `app`；`GET /api/v1/health` 返回 `{"status": "ok"}`；pytest fixture `client`（httpx AsyncClient）。后续任务的 router 都挂到这个 app。

- [ ] **Step 1: 初始化项目与依赖**

```bash
cd /Users/xiaotaotao/cyble-code/SkillLens/server
uv init --python 3.12 --name skilllens-server
uv add fastapi "uvicorn[standard]" sqlalchemy alembic pydantic
uv add --dev pytest httpx
```

`server/app/config.py`：

```python
HOST = "127.0.0.1"
PORT = 8710
DATABASE_URL = "sqlite:///./skilllens.db"
API_PREFIX = "/api/v1"
```

- [ ] **Step 2: 写失败测试**

`server/tests/conftest.py`：

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
```

`server/tests/test_health.py`：

```python
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 3: 运行确认失败**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: FAIL（`app.main` 不存在）

- [ ] **Step 4: 最小实现**

`server/app/main.py`：

```python
from fastapi import FastAPI

from app.api import health
from app.config import API_PREFIX

app = FastAPI(title="SkillLens Local Agent")
app.include_router(health.router, prefix=API_PREFIX)
```

`server/app/api/health.py`：

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 5: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v`
Expected: 1 passed

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat: server 骨架与 health 接口"
```

---

### Task 2: 数据模型 + Alembic 首个迁移（recording_session / raw_event）

**Files:**
- Create: `server/app/models.py`、`server/alembic/*`（alembic init 产物 + 首个版本文件）
- Test: `server/tests/test_models.py`

**Interfaces:**
- Produces: ORM 模型 `RecordingSession`（字段 `id: str` UUID 主键、`started_at: datetime`、`target_system: str`、`note: str`）与 `RawEvent`（`id: int` 自增主键、`session_id: str` 外键、`seq: int`、`ts: bigint`、`kind: str`、`payload: JSON`、`created_at`；`UniqueConstraint("session_id", "seq")`）。后续任务直接 import 使用。

- [ ] **Step 1: 写失败测试**

`server/tests/test_models.py`：

```python
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, RawEvent, RecordingSession


def test_raw_event_append_only_shape():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        sess = RecordingSession(id="s1", target_system="njmind", note="poc")
        s.add(sess)
        s.add(RawEvent(session_id="s1", seq=1, ts=1700000000000, kind="action", payload={"x": 1}))
        s.commit()
        rows = s.execute(select(RawEvent).where(RawEvent.session_id == "s1")).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload == {"x": 1}
        assert rows[0].created_at is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_models.py -v`
Expected: FAIL（`app.models` 不存在）

- [ ] **Step 3: 实现模型**

`server/app/models.py`：

```python
from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordingSession(Base):
    __tablename__ = "recording_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    target_system: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(500), default="")


class RawEvent(Base):
    __tablename__ = "raw_event"
    __table_args__ = (UniqueConstraint("session_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 5: Alembic 迁移**

```bash
cd server && uv run alembic init alembic
```

编辑 `alembic/env.py`：在顶部加 `from app.models import Base`，把 `target_metadata` 改为 `Base.metadata`；编辑 `alembic.ini` 的 `sqlalchemy.url` 与 `app/config.py` 的 `DATABASE_URL` 一致。

```bash
uv run alembic revision --autogenerate -m "recording_session and raw_event"
uv run alembic upgrade head
sqlite3 skilllens.db ".tables"   # 应看到 recording_session 与 raw_event
```

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat: recording_session/raw_event 模型与 Alembic 首个迁移"
```

---

### Task 3: sessions 接口（创建采集会话）

**Files:**
- Create: `server/app/db.py`、`server/app/api/events.py`
- Modify: `server/app/main.py`（挂载 events router）
- Test: `server/tests/test_sessions.py`

**Interfaces:**
- Consumes: Task 2 的 `RecordingSession` 模型。
- Produces: `POST /api/v1/sessions`，body `{"target_system": str, "note": str}`，返回 `{"session_id": "<uuid>"}`。Task 4/插件 uploader 依赖此接口。

- [ ] **Step 1: 写失败测试**

`server/tests/test_sessions.py`：

```python
async def test_create_session(client):
    resp = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["session_id"]) == 36  # uuid
    # 幂等性不要求，但重复调用应产生不同 session
    resp2 = await client.post("/api/v1/sessions", json={"target_system": "njmind", "note": "poc"})
    assert resp2.json()["session_id"] != body["session_id"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_sessions.py -v`
Expected: FAIL（404，路由不存在）

- [ ] **Step 3: 实现**

`server/app/db.py`：

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
```

`server/app/api/events.py`：

```python
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RecordingSession

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class SessionCreate(BaseModel):
    target_system: str = ""
    note: str = ""


@router.post("/sessions")
async def create_session(body: SessionCreate, db: Session = Depends(get_db)) -> dict:
    session_id = str(uuid.uuid4())
    db.add(RecordingSession(id=session_id, target_system=body.target_system, note=body.note))
    db.commit()
    return {"session_id": session_id}
```

`server/app/main.py` 追加：

```python
from app.api import events
app.include_router(events.router, prefix=API_PREFIX)
```

- [ ] **Step 4: 运行测试通过 + Commit**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

```bash
git add server/
git commit -m "feat: sessions 创建接口"
```

---

### Task 4: events 批量上报接口（append-only 落库）

**Files:**
- Modify: `server/app/api/events.py`、`server/app/schemas.py`（新建）
- Test: `server/tests/test_events.py`

**Interfaces:**
- Consumes: Task 2 的 `RawEvent`、Task 3 的 `get_db`。
- Produces: `POST /api/v1/sessions/{session_id}/events`，body 为事件数组，返回 `{"accepted": <int>}`。事件 schema（`app/schemas.py`）是插件 `extension/src/shared/types.ts` 的对齐基准：

```python
class RawEventIn(BaseModel):
    seq: int
    ts: int          # epoch 毫秒
    kind: Literal["ui", "action", "network", "console", "navigation"]
    payload: dict
```

- [ ] **Step 1: 写失败测试**

`server/tests/test_events.py`：

```python
async def test_batch_ingest(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 1, "ts": 1700000000000, "kind": "action",
         "payload": {"type": "click", "target": "button", "label": "提交"}},
        {"seq": 2, "ts": 1700000000120, "kind": "network",
         "payload": {"method": "POST", "url": "/api/order/92382/submit", "status": 200}},
    ]
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 2}


async def test_rejects_bad_kind(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    resp = await client.post(
        f"/api/v1/sessions/{sid}/events",
        json=[{"seq": 1, "ts": 1, "kind": "bogus", "payload": {}}],
    )
    assert resp.status_code == 422


async def test_rejects_duplicate_seq(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = [{"seq": 1, "ts": 1, "kind": "action", "payload": {}}]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    assert resp.status_code == 409  # 重复 (session_id, seq) 拒绝
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_events.py -v`
Expected: FAIL

- [ ] **Step 3: 实现**

`server/app/schemas.py`：

```python
from typing import Literal

from pydantic import BaseModel


class RawEventIn(BaseModel):
    seq: int
    ts: int
    kind: Literal["ui", "action", "network", "console", "navigation"]
    payload: dict
```

`server/app/api/events.py` 追加：

```python
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models import RawEvent
from app.schemas import RawEventIn


@router.post("/sessions/{session_id}/events")
async def ingest_events(session_id: str, events: list[RawEventIn],
                        db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    try:
        db.add_all(RawEvent(session_id=session_id, seq=e.seq, ts=e.ts,
                            kind=e.kind, payload=e.payload) for e in events)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="duplicate (session_id, seq)")
    return {"accepted": len(events)}
```

- [ ] **Step 4: 运行测试通过 + Commit**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

```bash
git add server/
git commit -m "feat: events 批量上报接口（append-only + 重复序号拒绝）"
```

---

### Task 5: 插件工程脚手架（Vite + CRXJS，可加载进 Chrome）

**Files:**
- Create: `extension/package.json`、`extension/vite.config.ts`、`extension/manifest.config.ts`、`extension/src/shared/types.ts`
- 无单测（纯脚手架），验收 = 构建产物可在 Chrome 加载

**Interfaces:**
- Produces: 可 `npm run build` 出 `extension/dist/` 的 MV3 插件骨架；`types.ts` 导出与 `app/schemas.py` 对齐的 TS 类型，后续所有插件任务 import 它。

- [ ] **Step 1: 初始化**

```bash
cd /Users/xiaotaotao/cyble-code/SkillLens/extension
npm init -y
npm install -D vite @crxjs/vite-plugin @types/chrome typescript vitest
```

`extension/package.json` 的 scripts 改为：

```json
{
  "scripts": {
    "build": "vite build",
    "test": "vitest run"
  }
}
```

`extension/vite.config.ts`：

```typescript
import { defineConfig } from "vite";
import { crx } from "@crxjs/vite-plugin";
import manifest from "./manifest.config";

export default defineConfig({ plugins: [crx({ manifest })] });
```

`extension/manifest.config.ts`：

```typescript
import { defineManifest } from "@crxjs/vite-plugin";

export default defineManifest({
  manifest_version: 3,
  name: "SkillLens Sensor",
  version: "0.1.0",
  host_permissions: ["http://127.0.0.1:8710/*"],
  content_scripts: [{ matches: ["<all_urls>"], js: ["src/content/capture.ts"] }],
  background: { service_worker: "src/background/uploader.ts", type: "module" },
});
```

`extension/src/shared/types.ts`（与 server `RawEventIn` 对齐）：

```typescript
export type EventKind = "ui" | "action" | "network" | "console" | "navigation";

export interface RawEvent {
  seq: number;
  ts: number;
  kind: EventKind;
  payload: Record<string, unknown>;
}

export const AGENT_URL = "http://127.0.0.1:8710/api/v1";
```

- [ ] **Step 2: 构建验证**

Run: `cd extension && npm run build`
Expected: `extension/dist/` 生成，无报错。Chrome → `chrome://extensions` → 开发者模式 → 加载 `dist/` 成功（此时 content/background 还是空文件也行，先建占位空导出文件）。

- [ ] **Step 3: Commit**

```bash
git add extension/
git commit -m "feat: 插件脚手架（MV3 + CRXJS）"
```

---

### Task 6: 元素语义描述工具（describe-element）

**Files:**
- Create: `extension/src/shared/describe-element.ts`
- Test: `extension/src/shared/describe-element.test.ts`（vitest，jsdom 环境）

**Interfaces:**
- Produces: `describeElement(el: Element): ElementDesc`，`ElementDesc = { tag: string; role: string; label: string; text: string; path: string }`。Task 8 采集 click/input 时用它生成 payload。

- [ ] **Step 1: 安装 jsdom 并写失败测试**

```bash
cd extension && npm install -D jsdom
```

`extension/src/shared/describe-element.test.ts`：

```typescript
// vitest.config.ts 需加 environment: "jsdom"（见 Step 3）
import { describeElement } from "./describe-element";

function make(html: string): Element {
  const div = document.createElement("div");
  div.innerHTML = html.trim();
  return div.firstElementChild!;
}

describe("describeElement", () => {
  it("提取按钮的 role/label/text", () => {
    const el = make(`<button aria-label="提交审批">提交</button>`);
    const d = describeElement(el);
    expect(d).toMatchObject({ tag: "button", role: "button", label: "提交审批", text: "提交" });
  });

  it("无 aria-label 时回退到可见文本", () => {
    const el = make(`<button>保存草稿</button>`);
    expect(describeElement(el).label).toBe("保存草稿");
  });

  it("输入框取 placeholder 或关联 label", () => {
    const el = make(`<input placeholder="订单号" />`);
    expect(describeElement(el).label).toBe("订单号");
  });

  it("path 是简化的标签路径", () => {
    const el = make(`<div><span><button>ok</button></span></div>`).querySelector("button")!;
    expect(describeElement(el).path).toBe("div>span>button");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd extension && npx vitest run src/shared/describe-element.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`extension/vitest.config.ts`：

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({ test: { environment: "jsdom" } });
```

`extension/src/shared/describe-element.ts`：

```typescript
export interface ElementDesc {
  tag: string;
  role: string;
  label: string;
  text: string;
  path: string;
}

export function describeElement(el: Element): ElementDesc {
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute("role") ?? implicitRole(el);
  const text = (el.textContent ?? "").trim().slice(0, 100);
  const label = el.getAttribute("aria-label")
    ?? el.getAttribute("placeholder")
    ?? el.getAttribute("title")
    ?? text;
  return { tag, role, label, text, path: domPath(el) };
}

function implicitRole(el: Element): string {
  const tag = el.tagName.toLowerCase();
  if (["button", "a", "input", "select", "textarea"].includes(tag)) return tag;
  return "";
}

function domPath(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  while (cur && cur.parentElement && parts.length < 5) {
    parts.unshift(cur.tagName.toLowerCase());
    cur = cur.parentElement;
  }
  return parts.join(">");
}
```

- [ ] **Step 4: 运行测试通过 + Commit**

Run: `cd extension && npm test` → 全部 passed

```bash
git add extension/
git commit -m "feat: 元素语义描述工具 describeElement"
```

---

### Task 7: 脱敏工具（redact）

**Files:**
- Create: `extension/src/shared/redact.ts`
- Test: `extension/src/shared/redact.test.ts`

**Interfaces:**
- Produces: `redactValue(key: string, value: unknown): unknown`（key 命中敏感词则返回 `"[REDACTED]"`）与 `SENSITIVE_KEY_RE = /password|passwd|secret|token|authorization|cookie/i`。Task 8/9 采集时对 payload 逐字段调用。

- [ ] **Step 1: 写失败测试**

`extension/src/shared/redact.test.ts`：

```typescript
import { redactValue } from "./redact";

describe("redactValue", () => {
  it("敏感 key 被掩码", () => {
    expect(redactValue("password", "abc123")).toBe("[REDACTED]");
    expect(redactValue("Authorization", "Bearer xx")).toBe("[REDACTED]");
    expect(redactValue("access_token", "t")).toBe("[REDACTED]");
  });
  it("普通 key 原样返回", () => {
    expect(redactValue("order_id", 92382)).toBe(92382);
    expect(redactValue("customer", "张三")).toBe("张三");
  });
  it("嵌套 dict 递归脱敏", () => {
    expect(redactValue("body", { user: "a", password: "b" })).toEqual({ user: "a", password: "[REDACTED]" });
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd extension && npx vitest run src/shared/redact.test.ts` → FAIL

- [ ] **Step 3: 实现**

`extension/src/shared/redact.ts`：

```typescript
export const SENSITIVE_KEY_RE = /password|passwd|secret|token|authorization|cookie/i;
const MASK = "[REDACTED]";

export function redactValue(key: string, value: unknown): unknown {
  if (SENSITIVE_KEY_RE.test(key)) return MASK;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, redactValue(k, v)]),
    );
  }
  return value;
}
```

- [ ] **Step 4: 运行测试通过 + Commit**

Run: `cd extension && npm test` → 全部 passed

```bash
git add extension/
git commit -m "feat: 插件侧基础脱敏 redactValue"
```

---

### Task 8: content script 动作采集（click / input / submit / navigation）

**Files:**
- Create: `extension/src/content/capture.ts`、`extension/src/store/idb.ts`
- Modify: `extension/manifest.config.ts`（content_scripts 已在 Task 5 声明，无需改）

**Interfaces:**
- Consumes: Task 6 `describeElement`、Task 7 `redactValue`、Task 5 `RawEvent`/`AGENT_URL`。
- Produces: content script 把采集到的事件写入 IndexedDB store `events`（keyPath 自增 `id`），并 `chrome.runtime.sendMessage({ type: "events-pending" })` 通知 background。`idb.ts` 导出 `putEvent(event: RawEvent): Promise<void>` 与 `takeEvents(batch: number): Promise<{id: number; event: RawEvent}[]>`（取出并删除）。Task 10 的 uploader 消费同一 store。

- [ ] **Step 1: IndexedDB 极简封装**

`extension/src/store/idb.ts`：

```typescript
import type { RawEvent } from "../shared/types";

const DB_NAME = "skilllens";
const STORE = "events";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function putEvent(event: RawEvent): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add({ event });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function takeEvents(batch: number): Promise<{ id: number; event: RawEvent }[]> {
  const db = await open();
  const all = await new Promise<{ id: number; event: RawEvent }[]>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve(req.result as never);
    req.onerror = () => reject(req.error);
  });
  const out = all.slice(0, batch);
  const tx = db.transaction(STORE, "readwrite");
  const store = tx.objectStore(STORE);
  for (const row of out) store.delete(row.id);
  await new Promise<void>((r) => (tx.oncomplete = () => r()));
  db.close();
  return out;
}
```

- [ ] **Step 2: 采集入口**

`extension/src/content/capture.ts`：

```typescript
import { putEvent } from "../store/idb";
import { describeElement } from "../shared/describe-element";
import { redactValue } from "../shared/redact";
import type { RawEvent } from "../shared/types";

let seq = 0;
let sessionId = "";

async function ensureSession(): Promise<void> {
  if (sessionId) return;
  const resp = await fetch("http://127.0.0.1:8710/api/v1/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_system: location.host, note: "auto" }),
  });
  sessionId = (await resp.json()).session_id;
}

async function emit(kind: RawEvent["kind"], payload: Record<string, unknown>): Promise<void> {
  await ensureSession();
  const event: RawEvent = { seq: seq++, ts: Date.now(), kind, payload };
  await putEvent(event);
  chrome.runtime.sendMessage({ type: "events-pending" }).catch(() => {});
}

document.addEventListener(
  "click",
  (e) => {
    const target = e.target as Element;
    if (!target) return;
    void emit("action", { type: "click", target: describeElement(target), url: location.href });
  },
  { capture: true },
);

document.addEventListener(
  "change",
  (e) => {
    const target = e.target as HTMLInputElement;
    if (!target?.name) return;
    const value = target.type === "password" ? "[REDACTED]" : target.value;
    void emit("action", {
      type: "input",
      target: describeElement(target),
      name: target.name,
      value: redactValue(target.name, value),
    });
  },
  { capture: true },
);

document.addEventListener(
  "submit",
  (e) => {
    void emit("action", { type: "submit", target: describeElement(e.target as Element), url: location.href });
  },
  { capture: true },
);

void emit("navigation", { type: "page-load", url: location.href, title: document.title });
```

- [ ] **Step 3: 手动验证（无自动化测试，浏览器行为）**

Run: `cd extension && npm run build`，Chrome 重新加载插件，打开任一网页点击/输入，DevTools → Application → IndexedDB → `skilllens.events` 应出现记录。

- [ ] **Step 4: Commit**

```bash
git add extension/
git commit -m "feat: content script 动作采集与 IndexedDB 缓冲"
```

---

### Task 9: MAIN world 网络观察（fetch / XHR 包装）

**Files:**
- Create: `extension/src/injected/net-hook.ts`
- Modify: `extension/src/content/capture.ts`（注入 + 接收）、`extension/manifest.config.ts`（声明 `web_accessible_resources`）

**Interfaces:**
- Consumes: Task 8 的 `emit`（复用同一 IndexedDB 管道）。
- Produces: `kind: "network"` 事件，payload `{ method, url, status, reqBody, resBody, duration }`，reqBody/resBody 经过 `redactValue`。注入脚本通过 `window.postMessage({ source: "skilllens-net" })` 回传 content script。

- [ ] **Step 1: 注入脚本**

`extension/src/injected/net-hook.ts`：

```typescript
const MASK = "[REDACTED]";
const SENSITIVE = /password|passwd|secret|token|authorization|cookie/i;

function redact(obj: unknown): unknown {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    return Object.fromEntries(
      Object.entries(obj as Record<string, unknown>).map(([k, v]) => [k, SENSITIVE.test(k) ? MASK : redact(v)]),
    );
  }
  return obj;
}

function post(detail: Record<string, unknown>): void {
  window.postMessage({ source: "skilllens-net", detail }, "*");
}

const origFetch = window.fetch;
window.fetch = async (...args) => {
  const started = performance.now();
  const resp = await origFetch(...args);
  try {
    const [input, init] = args;
    const url = typeof input === "string" ? input : (input as Request).url;
    const method = init?.method ?? "GET";
    const clone = resp.clone();
    const resBody = await clone.text().catch(() => "");
    post({
      method, url, status: resp.status, duration: Math.round(performance.now() - started),
      reqBody: redact(init?.body ?? null), resBody: resBody.slice(0, 2000),
    });
  } catch { /* 观察失败不影响页面 */ }
  return resp;
};

const OrigOpen = XMLHttpRequest.prototype.open;
const OrigSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function (this: XMLHttpRequest & { _m?: string; _u?: string }, method, url, ...rest) {
  this._m = method; this._u = String(url);
  return OrigOpen.call(this, method, url, ...(rest as []));
};
XMLHttpRequest.prototype.send = function (this: XMLHttpRequest & { _m?: string; _u?: string; _t0?: number }, body) {
  this._t0 = performance.now();
  this.addEventListener("load", () => {
    post({
      method: this._m, url: this._u, status: this.status,
      duration: Math.round(performance.now() - (this._t0 ?? 0)),
      reqBody: redact(body), resBody: String(this.responseText ?? "").slice(0, 2000),
    });
  });
  return OrigSend.call(this, body);
};
```

- [ ] **Step 2: content script 注入与接收**

`extension/src/content/capture.ts` 追加：

```typescript
// 注入 MAIN world 脚本
const s = document.createElement("script");
s.src = chrome.runtime.getURL("src/injected/net-hook.js");
s.async = false;
document.documentElement.appendChild(s);

// 接收网络事件
window.addEventListener("message", (e) => {
  if (e.source !== window || e.data?.source !== "skilllens-net") return;
  void emit("network", e.data.detail);
});
```

`extension/manifest.config.ts` 追加：

```typescript
web_accessible_resources: [{ resources: ["src/injected/net-hook.js"], matches: ["<all_urls>"] }],
```

- [ ] **Step 3: 手动验证**

Run: `cd extension && npm run build`，重载插件，打开任一有请求的页面，IndexedDB 里应出现 `kind: "network"` 记录且 Authorization/密码字段为 `[REDACTED]`。

- [ ] **Step 4: Commit**

```bash
git add extension/
git commit -m "feat: MAIN world fetch/XHR 网络观察与脱敏"
```

---

### Task 10: background 批量上报器（缓冲 → 批量 POST → 失败回退）

**Files:**
- Create: `extension/src/background/uploader.ts`

**Interfaces:**
- Consumes: Task 8 的 `takeEvents`、Task 3/4 的 sessions/events 接口。
- Produces: service worker：收到 `events-pending` 消息或每 5s 定时，从 IndexedDB 取 ≤50 条，`POST /api/v1/sessions/{sid}/events`；失败则放回（重试上限 3 次，超过丢弃并 `console.warn`——POC 阶段可接受，Sprint 1 改为持久重试队列）。

- [ ] **Step 1: 实现**

`extension/src/background/uploader.ts`：

```typescript
import { putEvent, takeEvents } from "../store/idb";
import type { RawEvent } from "../shared/types";

const AGENT = "http://127.0.0.1:8710/api/v1";
const BATCH = 50;

async function flush(): Promise<void> {
  const rows = await takeEvents(BATCH);
  if (rows.length === 0) return;
  // 同一 session 的事件分组上报（POC：一个 content script 一个 session）
  const bySession = new Map<string, RawEvent[]>();
  for (const r of rows) {
    const sid = (r.event.payload.__session_id as string) ?? "";
    if (!sid) continue; // POC：无 session 标记的丢弃不了——见 Step 2 修正
  }
  // 见 Step 2：session_id 需写入事件
}

async function loop(): Promise<void> {
  await flush();
  chrome.alarms.create("flush", { periodInMinutes: 0.1 });
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "events-pending") void flush();
});
chrome.alarms.onAlarm.addListener(() => void flush());
void loop();
```

- [ ] **Step 2: 修正——事件必须携带 session_id**

`extension/src/content/capture.ts` 的 `emit` 中，把 `__session_id` 写入 payload：

```typescript
const event: RawEvent = {
  seq: seq++, ts: Date.now(), kind,
  payload: { ...payload, __session_id: sessionId },
};
```

`uploader.ts` 的 `flush` 完整实现：

```typescript
async function flush(): Promise<void> {
  const rows = await takeEvents(BATCH);
  if (rows.length === 0) return;
  const bySession = new Map<string, RawEvent[]>();
  for (const { event } of rows) {
    const sid = event.payload.__session_id as string;
    const list = bySession.get(sid) ?? [];
    list.push(event);
    bySession.set(sid, list);
  }
  for (const [sid, events] of bySession) {
    try {
      const resp = await fetch(`${AGENT}/sessions/${sid}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(events),
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
    } catch (err) {
      console.warn("skilllens upload failed, requeue", err);
      for (const e of events) await putEvent(e); // 失败回退
    }
  }
}
```

`manifest.config.ts` 的 permissions 追加 `"alarms"`。

- [ ] **Step 3: 手动验证**

Run: `cd extension && npm run build`，重载插件；先 `cd server && uv run uvicorn app.main:app --port 8710`；浏览网页 30s 后查询：

```bash
sqlite3 server/skilllens.db "SELECT kind, count(*) FROM raw_event GROUP BY kind;"
```

Expected: `action` / `network` / `navigation` 各有计数。

- [ ] **Step 4: Commit**

```bash
git add extension/
git commit -m "feat: background 批量上报器（缓冲/重试/分组）"
```

---

### Task 11: njmind 端到端验收 + 演示记录

**Files:**
- Create: `demo/sprint0/README.md`（演示记录：操作步骤、截图文件名、SQL 查询结果）

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: Sprint 0 验收证据，对应 spec §7 Sprint 0 验收标准："raw_event 表里能看到一次完整表单操作的原始事件"。

- [ ] **Step 1: 启动两端**

```bash
cd server && uv run uvicorn app.main:app --port 8710   # 终端 1
cd extension && npm run build                          # 终端 2（如已构建可跳过）
```

- [ ] **Step 2: 在 njmind 上执行一次完整表单操作**

打开 njmind 任一表单页面 → 填写 2~3 个字段 → 提交。等待 10s 让上报完成。

- [ ] **Step 3: 数据验收（全部通过才算完成）**

```bash
sqlite3 server/skilllens.db "SELECT seq, kind, json_extract(payload,'$.type') FROM raw_event ORDER BY id LIMIT 30;"
```

逐项确认：

1. 存在 `navigation`（page-load）事件；
2. 存在 `action` 的 `input` 事件且字段值正确、密码字段为 `[REDACTED]`；
3. 存在 `action` 的 `click`/`submit` 事件且 label 是按钮语义文本（非 CSS selector）；
4. 存在 `network` 事件，能看到表单提交的 POST（URL、status、reqBody/resBody）；
5. `seq` 在同一 session 内单调递增，无重复。

- [ ] **Step 4: 记录演示证据并提交**

把 Step 3 的查询输出、关键截图存入 `demo/sprint0/`，写 `README.md` 说明复现步骤。

```bash
git add demo/
git commit -m "test: Sprint 0 njmind 端到端验收记录"
git push
```

- [ ] **Step 5: Sprint 0 回顾**

对照 spec §12 防跑偏清单逐条自问（重点：#7 抽查一条 network 事件能否回溯到 session；#9 pytest 是否全量通过）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.1 采集内容（UI/Action/Network/导航）→ Task 8/9；插件侧脱敏 → Task 7/9；本地 Agent 8710 → Task 1/5；`raw_event` 落库 + append-only + 唯一约束 → Task 2/4；§7 Sprint 0 验收标准 → Task 11。未覆盖（属 Sprint 1+，非本计划范围）：Transaction Window、URL 模板化、状态快照。
- **占位符**：Task 10 Step 1 故意留了一个有缺陷的初版并在 Step 2 修正（教学式拆步），最终代码完整；无 TBD。
- **类型一致性**：`RawEvent`（TS）与 `RawEventIn`（Pydantic）字段 `seq/ts/kind/payload` 对齐；`takeEvents/putEvent` 签名在 Task 8 定义、Task 10 消费一致；`__session_id` 在 Task 10 Step 2 写入并在 flush 中读取，名称一致。



