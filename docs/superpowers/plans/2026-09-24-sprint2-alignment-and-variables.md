# Sprint 2 实施计划：多 Episode 对齐 + 变量识别 + 两项必修加固

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对 2~10 次同一任务的演示（session）做确定性对齐，归并出流程骨架并识别变量（无 LLM）；补齐 C3 中间表落库与参数快照；修复跨页 seq 冲突导致的 409 丢批。

**Architecture:** 对齐在**语义窗口层**进行（不回原始事件层）：每窗口生成确定性签名（anchor+label+API 模板集合），参考集与其余集做 LCS，全 episode 共有的签名构成骨架；变量识别用两个确定性来源——骨架步内 API 参数的跨 episode 值差异、input 事件值序列的按位差异。跨页冲突用事件级 `page_id`（每页面实例一个）把唯一约束从 `(session_id, seq)` 改为 `(session_id, page_id, seq)`，保幂等（真重复仍被拒）。

**Tech Stack:** 既有栈不变（FastAPI/SQLAlchemy/Alembic/pytest；TS/CRXJS/vitest）。基线：pytest 26、vitest 16。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md`（§4.3 Learning Engine 多 Episode 对齐、§7 Sprint 2 行、§2 约束 C3）

## Global Constraints（每个任务默认遵守）

- **本 Sprint 全程无 LLM**：对齐与变量识别只用确定性算法；LLM Gateway / Skill 归纳 / 命名属 Sprint 3。
- C3 全链路持久化：`normalized_event`、`transaction_window`、`alignment` 均落库；中间表幂等删旧插新限本 session/task。
- `raw_event` 唯一约束改为 `(session_id, page_id, seq)`（约束名 `uq_raw_event_session_page_seq`）；append-only 不变。
- 窗口参数快照：`transaction_window` 行内记录 `idle_ms`、`max_window_ms`（值来自 `app/ingestion/windows.py` 常量，写入时读取）。
- process 排序键改为 `(ts, seq)`（ts 优先，seq 仅同 ms 内稳定排序）。
- `page_id` 生成必须兼容**非安全上下文**（njmind 是 http 内网地址，`crypto.randomUUID` 可能不存在）——需回退实现。
- 对齐输入为**显式 session_id 列表**（演示集 demo_set 表留 Sprint 3，YAGNI）。
- server 完成标准 = `cd server && uv run pytest tests/ -v` 全过；插件 = `npx vitest run` 全过 + `npm run build` + `npx tsc --noEmit`。
- 提交信息用中文，格式 `feat|test|chore|fix: 描述`。
- 真实浏览器验证由用户在 T7 手动执行；实现者以构建+单测为门槛。

## File Structure

```text
server/app/models.py                        # T1 RawEvent.page_id+约束；T3 两中间表；T6 Alignment
server/alembic/versions/*_page_id.py        # T1 表重建迁移（SQLite 换约束）
server/alembic/versions/*_intermediate.py   # T3 normalized_event/transaction_window
server/alembic/versions/*_alignment.py      # T6 alignment
server/app/schemas.py                       # T1 RawEventIn.page_id；T6 AlignRequest
server/app/api/events.py                    # T1 存 page_id
server/app/ingestion/process.py             # T3 排序键+中间表写入
server/app/ingestion/alignment.py           # T4 window_signature/lcs_pairs/align_skeletons
server/app/ingestion/variables.py           # T5 param_variables/input_variables
server/app/api/ingest.py                    # T6 POST /align + GET /alignments/{id}
server/tests/test_events.py                 # T1 追加跨页用例
server/tests/test_process.py                # T3 追加中间表断言
server/tests/test_alignment.py              # T4 纯函数
server/tests/test_variables.py              # T5 纯函数
server/tests/test_align_api.py              # T6 端点
extension/src/shared/page-id.ts(+test)      # T2 makePageId（secure 回退）
extension/src/shared/types.ts               # T2 RawEvent.page_id
extension/src/content/capture.ts            # T2 emit 带 page_id
demo/sprint2/                               # T7 验收记录
```

---

### Task 1: raw_event 加 page_id + 复合唯一约束（修跨页 409 丢批）

**Files:**
- Modify: `server/app/models.py`（RawEvent）、`server/app/schemas.py`（RawEventIn）、`server/app/api/events.py`（ingest 存 page_id）、`server/tests/test_events.py`（追加用例）
- Create: `server/alembic/versions/*_raw_event_page_id.py`

**Interfaces:**
- Produces: `RawEvent.page_id: str(40) 默认 ""`；唯一约束 `(session_id, page_id, seq)` 名 `uq_raw_event_session_page_seq`；`RawEventIn` 增加 `page_id: str = ""`（≤40 字符）；ingest_events 存入该列。T2 的插件事件携带 `page_id` 字段消费本接口。

- [ ] **Step 1: 写失败测试（test_events.py 追加）**

```python
async def test_same_seq_different_page_accepted(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = {"seq": 1, "ts": 1, "kind": "action", "payload": {}}
    r1 = await client.post(f"/api/v1/sessions/{sid}/events", json=[{**ev, "page_id": "page-a"}])
    r2 = await client.post(f"/api/v1/sessions/{sid}/events", json=[{**ev, "page_id": "page-b"}])
    assert r1.status_code == 200 and r2.status_code == 200  # 跨页同 seq 不再冲突


async def test_same_page_same_seq_still_409(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = [{"seq": 1, "ts": 1, "kind": "action", "payload": {}, "page_id": "page-a"}]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    resp = await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    assert resp.status_code == 409  # 同页同 seq 仍拒（幂等保持）
```

注：既有 `test_rejects_duplicate_seq`（无 page_id）在新约束下语义仍成立（同空 page_id + 同 seq → 409），应保持通过不改。

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_events.py -v`
Expected: `test_same_seq_different_page_accepted` FAIL（page_id 被 Pydantic 忽略 → 第二次仍 409）

- [ ] **Step 3: 实现**

`server/app/schemas.py` RawEventIn 增加字段（顶部 import 改为 `from pydantic import BaseModel, Field`）：

```python
class RawEventIn(BaseModel):
    seq: int
    ts: int
    page_id: str = Field(default="", max_length=40)
    kind: Literal["ui", "action", "network", "console", "navigation"]
    payload: dict
```

`server/app/api/events.py` ingest_events 的构造改为：

```python
db.add_all(RawEvent(session_id=session_id, seq=e.seq, page_id=e.page_id,
                    ts=e.ts, kind=e.kind, payload=e.payload) for e in events)
```

`server/app/models.py` RawEvent 整类替换为：

```python
class RawEvent(Base):
    __tablename__ = "raw_event"
    __table_args__ = (
        UniqueConstraint("session_id", "page_id", "seq", name="uq_raw_event_session_page_seq"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 28）

- [ ] **Step 5: Alembic 迁移（SQLite 换约束需表重建）**

```bash
cd server && uv run alembic revision -m "raw_event page_id and composite unique"
```

手写迁移文件（autogenerate 对 SQLite 无名旧约束不可靠）：

```python
def upgrade() -> None:
    op.execute("""
        CREATE TABLE raw_event_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(36) NOT NULL,
            page_id VARCHAR(40) NOT NULL DEFAULT '',
            seq INTEGER NOT NULL,
            ts BIGINT NOT NULL,
            kind VARCHAR(20) NOT NULL,
            payload JSON,
            created_at DATETIME,
            CONSTRAINT uq_raw_event_session_page_seq UNIQUE (session_id, page_id, seq)
        )
    """)
    op.execute("""
        INSERT INTO raw_event_new (id, session_id, page_id, seq, ts, kind, payload, created_at)
        SELECT id, session_id, '', seq, ts, kind, payload, created_at FROM raw_event
    """)
    op.execute("DROP TABLE raw_event")
    op.execute("ALTER TABLE raw_event_new RENAME TO raw_event")
    op.execute("CREATE INDEX ix_raw_event_session_id ON raw_event (session_id)")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE raw_event_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id VARCHAR(36) NOT NULL,
            seq INTEGER NOT NULL,
            ts BIGINT NOT NULL,
            kind VARCHAR(20) NOT NULL,
            payload JSON,
            created_at DATETIME,
            CONSTRAINT uq_raw_event_session_seq UNIQUE (session_id, seq)
        )
    """)
    op.execute("""
        INSERT INTO raw_event_old (id, session_id, seq, ts, kind, payload, created_at)
        SELECT id, session_id, seq, ts, kind, payload, created_at FROM raw_event
    """)
    op.execute("DROP TABLE raw_event")
    op.execute("ALTER TABLE raw_event_old RENAME TO raw_event")
    op.execute("CREATE INDEX ix_raw_event_session_id ON raw_event (session_id)")
```

然后：

```bash
uv run alembic upgrade head
sqlite3 skilllens.db "SELECT sql FROM sqlite_master WHERE name='raw_event';"  # 应含 uq_raw_event_session_page_seq
```

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat: raw_event 加 page_id 复合唯一约束，修复跨页 seq 冲突 409 丢批"
```

---

### Task 2: 插件侧 page_id（每页面实例一个，非安全上下文兼容）

**Files:**
- Create: `extension/src/shared/page-id.ts`、`extension/src/shared/page-id.test.ts`
- Modify: `extension/src/shared/types.ts`（RawEvent 加 `page_id: string`）、`extension/src/content/capture.ts`（emit 写入）

**Interfaces:**
- Consumes: Task 1 的 `RawEventIn.page_id`（≤40 字符）。
- Produces: `makePageId(): string`——同页面实例内多次调用返回同值；不同页面实例不同值；非安全上下文（http 内网）可用。

- [ ] **Step 1: 写失败测试**

`extension/src/shared/page-id.test.ts`：

```typescript
import { describe, expect, it } from "vitest";
import { makePageId } from "./page-id";

describe("makePageId", () => {
  it("同实例内稳定", () => {
    expect(makePageId()).toBe(makePageId());
  });
  it("长度 ≤ 40 且非空", () => {
    const id = makePageId();
    expect(id.length).toBeGreaterThan(0);
    expect(id.length).toBeLessThanOrEqual(40);
  });
  it("模块重置后生成新 id（模拟新页面实例）", async () => {
    const first = makePageId();
    vi.resetModules();
    const { makePageId: fresh } = await import("./page-id");
    expect(fresh()).not.toBe(first);
  });
});
```

（文件顶部需 `import { vi } from "vitest";` 或与首行 import 合并为 `import { describe, expect, it, vi } from "vitest";`。）

- [ ] **Step 2: 运行确认失败**

Run: `cd extension && npx vitest run src/shared/page-id.test.ts` → FAIL（模块不存在）

- [ ] **Step 3: 实现**

`extension/src/shared/page-id.ts`：

```typescript
let cached: string | null = null;

export function makePageId(): string {
  if (cached) return cached;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    cached = crypto.randomUUID();
  } else {
    cached = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }
  return cached;
}
```

`extension/src/shared/types.ts` 的 RawEvent 接口加字段（放在 seq 之后）：

```typescript
export interface RawEvent {
  seq: number;
  page_id: string;
  ts: number;
  kind: EventKind;
  payload: Record<string, unknown>;
}
```

`extension/src/content/capture.ts` 的 emit 构造改为（import makePageId）：

```typescript
const event: RawEvent = {
  seq: nextSeq(), page_id: makePageId(), ts: Date.now(), kind,
  payload: { ...payload, __session_id: "" },
};
```

`extension/src/shared/assign-session.ts` / `assign-session.test.ts`：构造测试事件的 `ev()` 工厂补 `page_id: "p1"` 字段（TS 类型收紧后必须补，行为断言不变）。`extension/src/background/uploader.ts` 无需改（透传整个 event）。

- [ ] **Step 4: 运行测试通过 + 构建**

Run: `cd extension && npx vitest run && npm run build && npx tsc --noEmit`
Expected: 全部 passed（16+3=19 左右）、build 成功、tsc 无错

- [ ] **Step 5: Commit**

```bash
git add extension/
git commit -m "feat: 插件事件携带页面实例 page_id（非安全上下文兼容）"
```

---

### Task 3: 中间表落库（normalized_event / transaction_window + 参数快照）

**Files:**
- Modify: `server/app/models.py`（追加两表）、`server/app/ingestion/process.py`（排序键 + 中间表写入）、`server/tests/test_process.py`（追加断言）
- Create: `server/alembic/versions/*_intermediate_tables.py`

**Interfaces:**
- Consumes: `build_windows`、`split_url/templatize_path`、既有 RawEvent。
- Produces:
  - ORM `NormalizedEvent`：`id` 自增、`session_id` 索引、`event_id`（FK raw_event.id 的 int，逻辑外键不建约束）、`template`（action：`click:{label}`；network：`{method}:{path 模板}`；其余 kind：`{kind}`）、`page_id`、`seq`、`ts`、`created_at`；
  - ORM `TransactionWindow`：`id` 自增、`session_id` 索引、`window_seq`、`anchor_event_id`、`member_event_ids` JSON、`idle_ms`、`max_window_ms`、`created_at`；
  - `process_session` 排序改为 `order_by(RawEvent.ts, RawEvent.seq)`，并在写入 semantic_action 的同时写入上述两表（幂等删旧插新限 session_id）。
- T4 的 alignment 消费 `TransactionWindow` + `SemanticAction`。

- [ ] **Step 1: 写失败测试（test_process.py 追加）**

```python
async def test_intermediate_tables_written(client):
    sid = await _seed(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    dump = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(dump) == 1

    from app.db import SessionLocal
    from app.models import NormalizedEvent, TransactionWindow
    from sqlalchemy import select
    db = SessionLocal()
    try:
        nes = db.execute(select(NormalizedEvent).where(NormalizedEvent.session_id == sid)).scalars().all()
        tws = db.execute(select(TransactionWindow).where(TransactionWindow.session_id == sid)).scalars().all()
        assert len(tws) == 1
        assert tws[0].idle_ms == 2000 and tws[0].max_window_ms == 8000
        assert len(tws[0].member_event_ids) == 1  # 只有锚点后的 POST
        templates = {ne.template for ne in nes}
        assert "click:保存" in templates
        assert "POST:/codeBack/formConfig/saveFormConfig" in templates
        assert "GET:/codeBack/role/list" in templates
    finally:
        db.close()


async def test_intermediate_idempotent(client):
    sid = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid}/process")
    await client.post(f"/api/v1/sessions/{sid}/process")
    from app.db import SessionLocal
    from app.models import NormalizedEvent, TransactionWindow
    from sqlalchemy import select
    db = SessionLocal()
    try:
        assert len(db.execute(select(NormalizedEvent).where(NormalizedEvent.session_id == sid)).scalars().all()) == 4
        assert len(db.execute(select(TransactionWindow).where(TransactionWindow.session_id == sid)).scalars().all()) == 1
    finally:
        db.close()
```

注意：`test_intermediate_tables_written` 直接用 SessionLocal 读**开发库**——测试须走 conftest 的测试库：conftest 已设 `DATABASE_URL` 环境变量指向 test.db，`app.db.SessionLocal` 导入时即绑定测试库，直接可用（同一进程）。若 `_seed` 内事件顺序与既有用例一致（4 条：navigation/GET/click/POST），NormalizedEvent 共 4 行、窗口 1 个、member 1 个。

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_process.py -v`
Expected: 新用例 FAIL（NormalizedEvent 不存在）

- [ ] **Step 3: 实现**

`server/app/models.py` 追加：

```python
class NormalizedEvent(Base):
    __tablename__ = "normalized_event"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[int] = mapped_column()
    template: Mapped[str] = mapped_column(String(500))
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TransactionWindow(Base):
    __tablename__ = "transaction_window"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_event_id: Mapped[int] = mapped_column()
    member_event_ids: Mapped[list] = mapped_column(JSON)
    idle_ms: Mapped[int] = mapped_column()
    max_window_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

`server/app/ingestion/process.py` 改造（完整替换）：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.signals import extract_state_signals
from app.ingestion.url_template import split_url, templatize_path
from app.ingestion.windows import IDLE_MS, MAX_WINDOW_MS, build_windows
from app.models import NormalizedEvent, RawEvent, SemanticAction, TransactionWindow


def normalize_event(row: RawEvent) -> str:
    payload = row.payload or {}
    if row.kind == "action":
        label = (payload.get("target") or {}).get("label", "")
        return f"{payload.get('type', row.kind)}:{label}"
    if row.kind == "network":
        path, _ = split_url(payload.get("url", ""))
        template, _ = templatize_path(path)
        return f"{payload.get('method', 'GET')}:{template}"
    return row.kind


def summarize_api(event: dict) -> dict:
    payload = event.get("payload") or {}
    template, params = templatize_path(split_url(payload.get("url", ""))[0])
    return {
        "seq": event["seq"],
        "method": payload.get("method"),
        "template": template,
        "status": payload.get("status"),
        "duration": payload.get("duration"),
        "params": params,
    }


def process_session(db: Session, session_id: str) -> dict:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    events = [{"event_id": r.id, "seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}, "page_id": r.page_id or ""} for r in rows]
    windows = build_windows(events)

    for model in (NormalizedEvent, TransactionWindow, SemanticAction):
        db.query(model).filter(model.session_id == session_id).delete()

    for e in events:
        db.add(NormalizedEvent(session_id=session_id, event_id=e["event_id"],
                               template=normalize_event_from(e), page_id=e["page_id"],
                               seq=e["seq"], ts=e["ts"]))

    for i, w in enumerate(windows):
        member_ids = [m["event_id"] for m in w["members"]]
        db.add(TransactionWindow(session_id=session_id, window_seq=i,
                                 anchor_event_id=w["anchor"]["event_id"],
                                 member_event_ids=member_ids,
                                 idle_ms=IDLE_MS, max_window_ms=MAX_WINDOW_MS))
        api_calls = [summarize_api(m) for m in w["members"]]
        state_signals = []
        for m, call in zip(w["members"], api_calls):
            for s in extract_state_signals((m.get("payload") or {}).get("resBody")):
                state_signals.append({"api": call["template"], **s})
        db.add(SemanticAction(
            session_id=session_id, window_seq=i,
            anchor_seq=w["anchor"]["seq"],
            anchor_type=(w["anchor"].get("payload") or {}).get("type", ""),
            target=(w["anchor"].get("payload") or {}).get("target"),
            api_calls=api_calls, state_signals=state_signals,
        ))
    db.commit()
    return {"windows": len(windows)}
```

其中 `normalize_event_from(e: dict) -> str` 为 normalize_event 的 dict 版（把上面的 normalize_event(row: RawEvent) 改为统一接受 dict：参数名 `e`，字段取 `e["kind"]`/`e["payload"]`，删除 RawEvent 版本，只留这一个实现，函数名 `normalize_event`）。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 30）

- [ ] **Step 5: Alembic 迁移**

```bash
cd server && uv run alembic revision --autogenerate -m "normalized_event transaction_window"
uv run alembic upgrade head
sqlite3 skilllens.db ".tables"   # 应含 normalized_event transaction_window
```

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat: normalized_event/transaction_window 中间表落库与窗口参数快照"
```

---

### Task 4: 对齐纯函数（window_signature / lcs / align_skeletons）

**Files:**
- Create: `server/app/ingestion/alignment.py`
- Test: `server/tests/test_alignment.py`

**Interfaces:**
- Consumes: 窗口 dict（来自 build_windows 的输出，含 anchor/members）。
- Produces:
  - `window_signature(window: dict) -> str`：`"{anchor_type}:{label}|{sorted(方法:模板)逗号连接}"`；
  - `lcs(a: list[str], b: list[str]) -> list[str]`：最长公共子序列（元素为签名）；
  - `align_skeletons(windows_per_session: list[list[dict]]) -> list[dict]`：以第一个 session 为参考集，与其余每个 session 逐一 LCS 取交集，返回骨架步列表 `[{"signature": str, "session_window_seqs": {sid: window_seq}}]`（某 session 无该签名时省略该键）。
- T6 端点消费。

- [ ] **Step 1: 写失败测试**

`server/tests/test_alignment.py`：

```python
from app.ingestion.alignment import align_skeletons, lcs, window_signature


def w(anchor_type, label, apis=()):
    return {
        "anchor": {"seq": 0, "ts": 0, "kind": "action",
                   "payload": {"type": anchor_type, "target": {"label": label}}},
        "members": [
            {"seq": 1, "ts": 1, "kind": "network",
             "payload": {"method": m, "url": u}} for m, u in apis
        ],
        "end_ts": 0,
    }


def test_window_signature():
    sig = window_signature(w("click", "保存", [("POST", "/a/1/save"), ("GET", "/a/1")]))
    assert sig == "click:保存|GET:/a/{id},POST:/a/{id}/save"  # 模板化+排序


def test_lcs_basic():
    assert lcs(["a", "b", "c", "d"], ["b", "d", "e"]) == ["b", "d"]


def test_align_finds_common_skeleton():
    s1 = [w("click", "打开"), w("click", "保存", [("POST", "/save")]), w("click", "关闭")]
    s2 = [w("click", "打开"), w("click", "保存", [("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    sigs = [step["signature"] for step in result]
    assert sigs == ["click:打开", "click:保存|POST:/save"]


def test_align_records_window_seqs():
    s1 = [w("click", "打开"), w("click", "保存", [("POST", "/save")])]
    s2 = [w("click", "保存", [("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    save_step = next(s for s in result if s["signature"].startswith("click:保存"))
    assert save_step["session_window_seqs"] == {"s1": 1, "s2": 0}


def test_align_single_session_returns_all():
    s1 = [w("click", "a"), w("click", "b")]
    result = align_skeletons([("s1", s1)])
    assert [s["signature"] for s in result] == ["click:a", "click:b"]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_alignment.py -v` → FAIL（模块不存在）

- [ ] **Step 3: 实现**

`server/app/ingestion/alignment.py`：

```python
from app.ingestion.url_template import split_url, templatize_path


def window_signature(window: dict) -> str:
    anchor = window.get("anchor") or {}
    payload = anchor.get("payload") or {}
    label = (payload.get("target") or {}).get("label", "")
    anchor_part = f"{payload.get('type', anchor.get('kind', ''))}:{label}"
    api_parts = []
    for m in window.get("members") or []:
        p = m.get("payload") or {}
        path, _ = split_url(p.get("url", ""))
        template, _ = templatize_path(path)
        api_parts.append(f"{p.get('method', 'GET')}:{template}")
    return f"{anchor_part}|{','.join(sorted(api_parts))}"


def lcs(a: list[str], b: list[str]) -> list[str]:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    out: list[str] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append(a[i])
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def align_skeletons(windows_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    if not windows_per_session:
        return []
    sig_lists: list[tuple[str, list[str]]] = []
    for sid, windows in windows_per_session:
        sig_lists.append((sid, [window_signature(w) for w in windows]))

    ref_sid, ref = sig_lists[0]
    common = list(ref)
    for _, sigs in sig_lists[1:]:
        common = lcs(common, sigs)
        if not common:
            break

    steps: list[dict] = []
    for signature in common:
        seqs: dict[str, int] = {}
        for sid, sigs in sig_lists:
            if signature in sigs:
                seqs[sid] = sigs.index(signature)
        steps.append({"signature": signature, "session_window_seqs": seqs})
    return steps
```

注意：`sigs.index(signature)` 取首个匹配（重复签名场景取第一次出现，MVP 语义，注释注明）。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 35）

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/alignment.py server/tests/test_alignment.py
git commit -m "feat: 窗口签名与多 Episode LCS 对齐（骨架提取）"
```

---

### Task 5: 变量识别纯函数（param_variables / input_variables）

**Files:**
- Create: `server/app/ingestion/variables.py`
- Test: `server/tests/test_variables.py`

**Interfaces:**
- Consumes: 骨架步（T4 输出）、各 session 的窗口与原始事件。
- Produces:
  - `param_variables(skeleton: list[dict], windows_per_session: list[tuple[str, list[dict]]]) -> list[dict]`：对每个骨架步，聚合各 session 中对应窗口 members 的 `summarize_api` params（值来自 `{"name": ..., "value": ...}`），返回 `[{"step": signature, "param": "id_0", "values": {sid: value}}]`（跨 session 值不同才输出，全相同的不算变量）；
  - `input_variables(events_per_session: list[tuple[str, list[dict]]]) -> list[dict]`：对每 session 的 input 型 action 事件按序取 `(name, value)`，返回 `[{"name": 字段名, "values": {sid: value}, "positions": {sid: 序号}}]`（同名输入且跨 session 值不同才输出）。
- T6 端点消费两者。

- [ ] **Step 1: 写失败测试**

`server/tests/test_variables.py`：

```python
from app.ingestion.variables import input_variables, param_variables


def ev(kind, payload, seq=0):
    return {"seq": seq, "ts": seq, "kind": kind, "payload": payload}


def test_param_variables_detects_changing_id():
    skeleton = [{"signature": "click:保存|POST:/orders/{id}/save", "session_window_seqs": {"s1": 0, "s2": 0}}]
    def win(order_id):
        return [{
            "anchor": {"seq": 0, "ts": 0, "kind": "action",
                       "payload": {"type": "click", "target": {"label": "保存"}}},
            "members": [ev("network", {"method": "POST", "url": f"/orders/{order_id}/save",
                                       "status": 200, "duration": 10, "reqBody": None, "resBody": ""})],
            "end_ts": 1,
        }]
    result = param_variables(skeleton, [("s1", win(111)), ("s2", win(222))])
    assert result == [{"step": "click:保存|POST:/orders/{id}/save",
                       "param": "id_0", "values": {"s1": "111", "s2": "222"}}]


def test_param_variables_constant_not_variable():
    skeleton = [{"signature": "click:保存|POST:/orders/{id}/save", "session_window_seqs": {"s1": 0, "s2": 0}}]
    def win():
        return [{
            "anchor": {"seq": 0, "ts": 0, "kind": "action",
                       "payload": {"type": "click", "target": {"label": "保存"}}},
            "members": [ev("network", {"method": "POST", "url": "/orders/111/save",
                                       "status": 200, "duration": 10, "reqBody": None, "resBody": ""})],
            "end_ts": 1,
        }]
    assert param_variables(skeleton, [("s1", win()), ("s2", win())]) == []


def test_input_variables_detects_values():
    s1 = [ev("action", {"type": "input", "name": "订单名", "value": "A"})]
    s2 = [ev("action", {"type": "input", "name": "订单名", "value": "B"})]
    result = input_variables([("s1", s1), ("s2", s2)])
    assert result == [{"name": "订单名", "values": {"s1": "A", "s2": "B"}, "positions": {"s1": 0, "s2": 0}}]


def test_input_variables_same_value_ignored():
    s1 = [ev("action", {"type": "input", "name": "备注", "value": "X"})]
    s2 = [ev("action", {"type": "input", "name": "备注", "value": "X"})]
    assert input_variables([("s1", s1), ("s2", s2)]) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_variables.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/ingestion/variables.py`：

```python
from app.ingestion.process import summarize_api


def param_variables(skeleton: list[dict], windows_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    windows_by_sid = dict(windows_per_session)
    out: list[dict] = []
    for step in skeletons_safe(skeleton):
        signature = step["signature"]
        values: dict[str, dict[str, str]] = {}
        for sid, window_seq in step.get("session_window_seqs", {}).items():
            windows = windows_by_sid.get(sid) or []
            if window_seq >= len(windows):
                continue
            for member in windows[window_seq].get("members") or []:
                for p in summarize_api(member).get("params") or []:
                    values.setdefault(p["name"], {})[sid] = str(p["value"])
        for param, per_session in values.items():
            if len(set(per_session.values())) > 1:
                out.append({"step": signature, "param": param, "values": per_session})
    return out


def skeletons_safe(skeleton: list[dict]) -> list[dict]:
    return [s for s in skeleton if isinstance(s, dict) and "signature" in s]


def input_variables(events_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    collected: dict[str, dict[str, list]] = {}
    positions: dict[str, dict[str, int]] = {}
    for sid, events in events_per_session:
        idx = 0
        for e in events:
            payload = e.get("payload") or {}
            if e.get("kind") != "action" or payload.get("type") != "input":
                continue
            name = payload.get("name")
            if not name:
                continue
            collected.setdefault(name, {}).setdefault(sid, []).append(str(payload.get("value")))
            positions.setdefault(name, {}).setdefault(sid, idx)
            idx += 1
    out: list[dict] = []
    for name, per_session in collected.items():
        first_vals = {sid: vals[0] for sid, vals in per_session.items()}
        if len(set(first_vals.values())) > 1:
            out.append({"name": name, "values": first_vals,
                        "positions": positions.get(name, {})})
    return out
```

注：`input_variables` 取每 session 同名输入的**首个值**做比较（MVP 语义，重复输入留 Sprint 3）。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 39）

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/variables.py server/tests/test_variables.py
git commit -m "feat: 确定性变量识别（API 参数差异 + 输入值差异）"
```

---

### Task 6: Alignment 落库 + align 端点

**Files:**
- Modify: `server/app/models.py`（追加 Alignment）、`server/app/schemas.py`（AlignRequest）、`server/app/api/ingest.py`（新端点）
- Create: `server/alembic/versions/*_alignment.py`、`server/tests/test_align_api.py`

**Interfaces:**
- Consumes: T4 `align_skeletons/window_signature`、T5 `param_variables/input_variables`、T1-T3 的表与 process。
- Produces:
  - ORM `Alignment`：`id` 自增、`session_ids` JSON、`skeleton` JSON、`param_variables` JSON、`input_variables` JSON、`created_at`；
  - `POST /api/v1/align`，body `{"session_ids": ["<sid>", ...]}`（2~10 个，全部须存在且已有 semantic_action，即先 process 过），返回 `{"alignment_id": <int>, "skeleton": [...], "param_variables": [...], "input_variables": [...]}`；任一 session 不存在 → 404；未 process（semantic_action 为空）→ 409 `"session not processed"`；
  - `GET /api/v1/alignments/{id}` → 同结构（404 不存在）。

- [ ] **Step 1: 写失败测试**

`server/tests/test_align_api.py`：

```python
async def _seed_session(client, order_id: int) -> str:
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "input", "name": "订单名", "value": f"订单-{order_id}"}},
        {"seq": 2, "ts": 2000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 2600, "kind": "network",
         "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                     "status": 200, "duration": 50, "reqBody": "{}",
                     "resBody": '{"code":200,"status":"SUCCESS"}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    assert (await client.post(f"/api/v1/sessions/{sid}/process")).status_code == 200
    return sid


async def test_align_two_sessions(client):
    s1 = await _seed_session(client, 111)
    s2 = await _seed_session(client, 222)
    resp = await client.post("/api/v1/align", json={"session_ids": [s1, s2]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alignment_id"] > 0
    sigs = [s["signature"] for s in body["skeleton"]]
    assert sigs == ["click:保存|POST:/orders/{id}/save"]
    assert body["param_variables"] == [{"step": "click:保存|POST:/orders/{id}/save",
                                        "param": "id_0", "values": {s1: "111", s2: "222"}}]
    assert body["input_variables"][0]["name"] == "订单名"
    assert body["input_variables"][0]["values"] == {s1: "订单-111", s2: "订单-222"}

    got = await client.get(f"/api/v1/alignments/{body['alignment_id']}")
    assert got.status_code == 200
    assert got.json()["skeleton"] == body["skeleton"]


async def test_align_unknown_session_404(client):
    resp = await client.post("/api/v1/align", json={"session_ids": ["nope"]})
    assert resp.status_code == 404


async def test_align_unprocessed_409(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    resp = await client.post("/api/v1/align", json={"session_ids": [sid]})
    assert resp.status_code == 409


async def test_alignment_get_404(client):
    resp = await client.get("/api/v1/alignments/99999")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_align_api.py -v` → FAIL（路由不存在）

- [ ] **Step 3: 实现**

`server/app/models.py` 追加：

```python
class Alignment(Base):
    __tablename__ = "alignment"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_ids: Mapped[list] = mapped_column(JSON)
    skeleton: Mapped[list] = mapped_column(JSON)
    param_variables: Mapped[list] = mapped_column(JSON)
    input_variables: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

`server/app/schemas.py` 追加：

```python
class AlignRequest(BaseModel):
    session_ids: list[str] = Field(min_length=2, max_length=10)
```

（需 `Field`，T1 已引入。）

`server/app/ingestion/process.py` 追加装配函数（复用既有查询逻辑，供 align 端点取窗口）：

```python
def load_windows(db: Session, session_id: str) -> list[dict]:
    rows = db.execute(
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    events = [{"event_id": r.id, "seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}, "page_id": r.page_id or ""} for r in rows]
    return build_windows(events)
```

（顶部 import 已含 build_windows 则复用；`load_windows` 与 process_session 共用同一查询，可把该查询提为模块内私有函数 `_events_of(db, session_id)` 供两者调用。）

`server/app/api/ingest.py` 追加：

```python
from app.ingestion.alignment import align_skeletons
from app.ingestion.process import load_windows
from app.ingestion.variables import input_variables, param_variables
from app.models import Alignment, SemanticAction
from app.schemas import AlignRequest


@router.post("/align")
async def align(body: AlignRequest, db: Session = Depends(get_db)) -> dict:
    for sid in body.session_ids:
        if not db.get(RecordingSession, sid):
            raise HTTPException(status_code=404, detail=f"session {sid} not found")
        if db.query(SemanticAction).filter(SemanticAction.session_id == sid).count() == 0:
            raise HTTPException(status_code=409, detail="session not processed")
    windows_per_session = [(sid, load_windows(db, sid)) for sid in body.session_ids]
    skeleton = align_skeletons(windows_per_session)
    pvars = param_variables(skeleton, windows_per_session)
    events_per_session = []
    for sid, _ in windows_per_session:
        rows = db.execute(
            select(RawEvent).where(RawEvent.session_id == sid).order_by(RawEvent.ts, RawEvent.seq)
        ).scalars().all()
        events_per_session.append((sid, [{"kind": r.kind, "payload": r.payload or {}} for r in rows]))
    ivars = input_variables(events_per_session)
    row = Alignment(session_ids=body.session_ids, skeleton=skeleton,
                    param_variables=pvars, input_variables=ivars)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"alignment_id": row.id, "skeleton": skeleton,
            "param_variables": pvars, "input_variables": ivars}


@router.get("/alignments/{alignment_id}")
async def get_alignment(alignment_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Alignment, alignment_id)
    if not row:
        raise HTTPException(status_code=404, detail="alignment not found")
    return {"alignment_id": row.id, "session_ids": row.session_ids,
            "skeleton": row.skeleton, "param_variables": row.param_variables,
            "input_variables": row.input_variables}
```

（文件顶部需补 `from sqlalchemy import select`。）

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed（约 44）

- [ ] **Step 5: Alembic 迁移**

```bash
cd server && uv run alembic revision --autogenerate -m "alignment"
uv run alembic upgrade head
sqlite3 skilllens.db ".tables"   # 应含 alignment
```

- [ ] **Step 6: Commit**

```bash
git add server/
git commit -m "feat: alignment 落库与 /align 端点（骨架+双源变量）"
```

---

### Task 7: njmind 端到端验收（多演示对齐）

**Files:**
- Create: `demo/sprint2/README.md`、`demo/sprint2/alignment-dump.txt`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: Sprint 2 验收证据：多次演示归并为骨架 + 变量识别正确。

- [ ] **Step 1: 启动与准备**

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710   # 重启加载新迁移与路由
cd extension && npm run build   # Chrome 重载插件 + 刷新 njmind 页面
```

- [ ] **Step 2: 用户操作（人工，两次完整演示）**

每次：popup 填备注（如"保存表单 v1"/"保存表单 v2"）→ 开始录制 → 在 njmind 表单页**改一个不同的字段值** → 点保存提交 → 停止。共做 2 次（两次输入值必须不同，如订单名 111/222）。期间**至少一次在录制中刷新页面或换 Tab 操作**（验证跨页 seq 修复）。

- [ ] **Step 3: 处理与验收**

```bash
S1=$(sqlite3 server/skilllens.db "SELECT id FROM recording_session ORDER BY rowid DESC LIMIT 2" | tail -1)
S2=$(sqlite3 server/skilllens.db "SELECT id FROM recording_session ORDER BY rowid DESC LIMIT 1")
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions/$S1/process
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions/$S2/process
curl -s -X POST http://127.0.0.1:8710/api/v1/align -H "Content-Type: application/json" \
  -d "{\"session_ids\": [\"$S1\", \"$S2\"]}" | python3 -m json.tool > demo/sprint2/alignment-dump.txt
```

验收项（全过才算完成）：

1. 两个 session 各自 process 出窗口，`保存` 窗口存在；
2. `skeleton` 非空且含保存步（签名 `click:保存|POST:...saveFormConfig...` 类）；
3. `param_variables` 含跨次不同的 formConfigId 值（或为空——若两次保存的是同一表单配置则 id 相同，此时以 `input_variables` 为准）；
4. `input_variables` 含用户两次输入不同的字段；
5. 录制中刷新页面那次操作的事件未丢失（跨页 409 修复生效：事件数与操作吻合、无 "upload failed" 丢弃日志）；
6. `GET /alignments/{id}` 可回读。

- [ ] **Step 4: 记录证据并提交**

```bash
git add demo/sprint2/
git commit -m "test: Sprint 2 njmind 端到端验收记录（多演示对齐+变量识别）"
git push
```

- [ ] **Step 5: Sprint 回顾**

对照 spec §12 防跑偏清单（重点 #1 主线推进、#7 从 alignment 回溯 raw_event、#9 测试全绿）；确认本 Sprint 全程未引入 LLM 依赖。

---

## Self-Review 记录

- **Spec 覆盖**：§4.3 多 Episode 对齐 → T4；变量识别（确定性 diff、LLM 只命名留 Sprint 3）→ T5；§7 Sprint 2 行（多次演示归并为 1 个 Skill、变量正确识别——Skill 实体本身留 Sprint 3，本 Sprint 产出其直接前置物 skeleton+variables）→ T6/T7；终审必修①（中间表+参数快照）→ T3；必修②（跨页 seq 409 丢批）→ T1/T2。未覆盖（Sprint 3+）：LLM Gateway、Skill 实体与命名、demo_set 演示集表、Outcome 断言。
- **占位符**：无 TBD；T3 的 normalize_event 有一处"dict 版统一"的行内说明（明确函数名与签名，非占位）。
- **类型一致性**：窗口 dict 字段（anchor.payload.target.label、members[].payload.method/url）在 T4/T5/T6 一致；`summarize_api(member)` 输入为事件 dict，T5 直接复用 T3 中定义的同名函数；`align_skeletons(windows_per_session: list[tuple[str, list[dict]]])` 与 T6 构造一致；`Alignment` 字段名与端点返回键一致；TS `RawEvent.page_id` 与 Pydantic `RawEventIn.page_id` 对齐（T2/T1）。
- **已知取舍**：重复签名取首个匹配（T4 注明）；input 变量取每 session 首个值（T5 注明）；alignment 每次 POST 新建行（不幂等，查询用途为主）。



