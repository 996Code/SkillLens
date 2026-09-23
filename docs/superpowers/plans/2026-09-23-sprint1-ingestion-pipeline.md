# Sprint 1 实施计划：Ingestion 管道 + 插件录制控制

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 raw_event 流自动切分为 Transaction Window 并关联 Action↔Network↔State，产出 `semantic_action` 表；插件加上录制开关（popup）+ 单 session 复用 + 断连不丢事件。

**Architecture:** server 端新增 `app/ingestion/` 纯函数管道（URL 模板化 → 窗口切分 → 状态信号提取 → 落库），由 `POST /sessions/{sid}/process` 手动触发（自动触发留 Sprint 2）；插件端 session 创建从 content script 移到 background（SW 的 fetch 不受 CORS 限制），popup 控制录制开关，事件缓冲在无 session 时由 flush 回填 session id。

**Tech Stack:** 既有栈不变（FastAPI/SQLAlchemy/Alembic/pytest；TS/CRXJS/vitest）。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md`（§4.2 Ingestion、§7 Sprint 1 行、§12 清单）

## Global Constraints（每个任务默认遵守）

- C3 全链路持久化：semantic_action 必须落库；管道每级纯函数可独立重放。
- `raw_event` 保持 append-only；`semantic_action` 允许"重算即删旧插新"（幂等，裁定记录于本节）。
- 窗口参数为模块常量：`IDLE_MS = 2000`、`MAX_WINDOW_MS = 8000`、锚点类型 `{"click", "submit"}`。
- URL 模板化规则：路径段为纯数字或 UUID → `{id}`，参数名 `id_0`、`id_1`…（按替换顺序）；查询串不模板化。
- 用户裁定：**server 端二次脱敏本 Sprint 不做**（插件侧既有脱敏保留）。
- server 端完成标准 = `cd server && uv run pytest tests/ -v` 全量通过；插件端 = `npx vitest run` 全过 + `npm run build` 成功。
- 提交信息用中文，格式 `feat|test|chore|fix: 描述`。
- 真实浏览器验证由用户在 T9 手动执行（njmind 内网），实现者以构建+单测为门槛。

## File Structure

```text
server/app/ingestion/__init__.py
server/app/ingestion/url_template.py        # T1 templatize_path/split_url
server/app/ingestion/windows.py             # T3 build_windows
server/app/ingestion/signals.py             # T4 extract_state_signals
server/app/ingestion/process.py             # T5 process_session + summarize_api
server/app/api/ingest.py                    # T5 process / semantic-actions 路由
server/app/models.py                        # T2 追加 SemanticAction
server/alembic/versions/*_semantic_action.py # T2 迁移
server/tests/test_url_template.py / test_windows.py / test_signals.py / test_process.py
extension/manifest.config.ts                # T6 加 "storage" 权限 + action.default_popup
extension/popup.html / popup.ts             # T6 录制开关 UI
extension/src/background/session.ts         # T6 start/stop/state + storage.session
extension/src/background/uploader.ts        # T6 挂 session 消息；T8 flush 回填 sid
extension/src/content/capture.ts            # T7 删 ensureSession、录制门控
extension/src/shared/assign-session.ts(+test) # T8 回填纯函数
demo/sprint1/                                # T9 验收记录
```

---

### Task 1: URL 模板化（templatize_path / split_url）

**Files:**
- Create: `server/app/ingestion/__init__.py`（空）、`server/app/ingestion/url_template.py`
- Test: `server/tests/test_url_template.py`

**Interfaces:**
- Produces: `split_url(url: str) -> tuple[str, str]`（(path, query)，兼容相对/绝对 URL）；`templatize_path(path: str) -> tuple[str, list[dict]]`（模板 + `[{"name": "id_0", "value": "92382"}]`）。T5 的 summarize_api 消费。

- [ ] **Step 1: 写失败测试**

`server/tests/test_url_template.py`：

```python
from app.ingestion.url_template import split_url, templatize_path


def test_numeric_segment():
    assert templatize_path("/order/92382/submit") == (
        "/order/{id}/submit",
        [{"name": "id_0", "value": "92382"}],
    )


def test_uuid_segment():
    tpl, params = templatize_path("/api/3f2b8c4e-1a2b-4c3d-9e8f-0a1b2c3d4e5f/detail")
    assert tpl == "/api/{id}/detail"
    assert params[0]["value"] == "3f2b8c4e-1a2b-4c3d-9e8f-0a1b2c3d4e5f"


def test_no_dynamic_segment():
    assert templatize_path("/codeBack/role/list") == ("/codeBack/role/list", [])


def test_multiple_numeric_segments():
    tpl, params = templatize_path("/a/1/b/22")
    assert tpl == "/a/{id}/b/{id}"
    assert [p["name"] for p in params] == ["id_0", "id_1"]
    assert [p["value"] for p in params] == ["1", "22"]


def test_split_url_relative_and_absolute():
    assert split_url("/x/y?code=cesh") == ("/x/y", "code=cesh")
    assert split_url("http://h:8080/x/1/y?q=2") == ("/x/1/y", "q=2")
    assert split_url("/x/y") == ("/x/y", "")
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_url_template.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`server/app/ingestion/url_template.py`：

```python
import re
from urllib.parse import urlsplit

NUMERIC = re.compile(r"^\d+$")
UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def split_url(url: str) -> tuple[str, str]:
    if url.startswith("http://") or url.startswith("https://"):
        parts = urlsplit(url)
        return parts.path or "/", parts.query or ""
    path, _, query = url.partition("?")
    return path or "/", query


def templatize_path(path: str) -> tuple[str, list[dict]]:
    segments = path.split("/")
    template_parts: list[str] = []
    params: list[dict] = []
    for seg in segments:
        if NUMERIC.match(seg) or UUID.match(seg):
            template_parts.append("{id}")
            params.append({"name": f"id_{len(params)}", "value": seg})
        else:
            template_parts.append(seg)
    return "/".join(template_parts), params
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/ server/tests/test_url_template.py
git commit -m "feat: URL 路径模板化（数字/UUID 段参数化）"
```

---

### Task 2: SemanticAction 模型 + 迁移

**Files:**
- Modify: `server/app/models.py`（文件末尾追加）
- Create: `server/alembic/versions/*_semantic_action.py`（autogenerate）
- Test: `server/tests/test_models.py`（追加一个用例）

**Interfaces:**
- Produces: ORM `SemanticAction`，字段：`id` int 自增主键、`session_id` str(36) 索引、`window_seq` int、`anchor_seq` int、`anchor_type` str(20)、`target` JSON nullable、`api_calls` JSON、`state_signals` JSON、`created_at` datetime。T5 写入、GET 端点读出。

- [ ] **Step 1: 写失败测试（追加到 test_models.py 末尾）**

```python
def test_semantic_action_shape():
    from app.models import SemanticAction

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(SemanticAction(
            session_id="s1", window_seq=0, anchor_seq=16, anchor_type="click",
            target={"label": "保存"},
            api_calls=[{"method": "POST", "template": "/codeBack/formConfig/saveFormConfig", "status": 200}],
            state_signals=[{"api": "/codeBack/formConfig/saveFormConfig", "field": "code", "value": 200}],
        ))
        s.commit()
        row = s.get(SemanticAction, 1)
        assert row.target["label"] == "保存"
        assert row.api_calls[0]["status"] == 200
        assert row.created_at is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_models.py::test_semantic_action_shape -v`
Expected: FAIL（SemanticAction 不存在）

- [ ] **Step 3: 实现（models.py 末尾追加）**

```python
class SemanticAction(Base):
    __tablename__ = "semantic_action"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_seq: Mapped[int] = mapped_column()
    anchor_type: Mapped[str] = mapped_column(String(20))
    target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    api_calls: Mapped[list] = mapped_column(JSON)
    state_signals: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

- [ ] **Step 5: Alembic 迁移**

```bash
cd server && uv run alembic revision --autogenerate -m "semantic_action"
uv run alembic upgrade head
sqlite3 skilllens.db ".tables"   # 应出现 semantic_action
```

- [ ] **Step 6: Commit**

```bash
git add server/app/models.py server/alembic/ server/tests/test_models.py
git commit -m "feat: semantic_action 模型与迁移"
```

---

### Task 3: Transaction Window 切分（build_windows）

**Files:**
- Create: `server/app/ingestion/windows.py`
- Test: `server/tests/test_windows.py`

**Interfaces:**
- Consumes: raw_event 形态的 dict：`{"seq": int, "ts": int, "kind": str, "payload": dict}`（按 seq 升序）。
- Produces: `build_windows(events: list[dict]) -> list[dict]`，每个 window `{"anchor": <event>, "members": [<network event>...], "end_ts": int}`。T5 消费。

- [ ] **Step 1: 写失败测试**

`server/tests/test_windows.py`：

```python
from app.ingestion.windows import build_windows


def ev(seq, ts, kind, ptype=None):
    payload = {"type": ptype} if ptype else {}
    return {"seq": seq, "ts": ts, "kind": kind, "payload": payload}


def test_click_then_post_in_same_window():
    events = [
        ev(0, 0, "navigation", "page-load"),
        ev(1, 100, "network"),
        ev(2, 1000, "action", "click"),
        ev(3, 1500, "network"),   # 距 anchor 500ms
        ev(4, 1700, "network"),   # 距上一网络 200ms
    ]
    windows = build_windows(events)
    assert len(windows) == 1
    assert windows[0]["anchor"]["seq"] == 2
    assert [m["seq"] for m in windows[0]["members"]] == [3, 4]
    assert windows[0]["end_ts"] == 1700


def test_idle_gap_closes_window():
    events = [
        ev(1, 1000, "action", "click"),
        ev(2, 1500, "network"),
        ev(3, 4500, "network"),   # 距上一网络 3000ms > IDLE_MS，关窗丢弃
    ]
    windows = build_windows(events)
    assert len(windows) == 1
    assert [m["seq"] for m in windows[0]["members"]] == [2]


def test_max_window_ms():
    events = [ev(1, 0, "action", "click"), ev(2, 9000, "network")]  # 超过 8000 上限
    assert [m["seq"] for m in build_windows(events)[0]["members"]] == []


def test_second_anchor_starts_new_window():
    events = [
        ev(1, 0, "action", "click"),
        ev(2, 100, "network"),
        ev(3, 5000, "action", "submit"),
        ev(4, 5100, "network"),
    ]
    windows = build_windows(events)
    assert [w["anchor"]["seq"] for w in windows] == [1, 3]
    assert [m["seq"] for m in windows[1]["members"]] == [4]


def test_input_events_ignored_as_anchor():
    events = [ev(1, 0, "action", "input"), ev(2, 100, "network")]
    assert build_windows(events) == []
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_windows.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

`server/app/ingestion/windows.py`：

```python
IDLE_MS = 2000
MAX_WINDOW_MS = 8000
ANCHOR_TYPES = {"click", "submit"}


def build_windows(events: list[dict]) -> list[dict]:
    windows: list[dict] = []
    current: dict | None = None
    last_net_ts: int | None = None
    for e in events:
        payload = e.get("payload") or {}
        is_anchor = e["kind"] == "action" and payload.get("type") in ANCHOR_TYPES
        is_network = e["kind"] == "network"
        if is_anchor:
            current = {"anchor": e, "members": [], "end_ts": e["ts"]}
            windows.append(current)
            last_net_ts = None
            continue
        if is_network and current is not None:
            reference = last_net_ts if last_net_ts is not None else current["anchor"]["ts"]
            within_idle = e["ts"] - reference <= IDLE_MS
            within_max = e["ts"] - current["anchor"]["ts"] <= MAX_WINDOW_MS
            if within_idle and within_max:
                current["members"].append(e)
                current["end_ts"] = e["ts"]
                last_net_ts = e["ts"]
            else:
                current = None  # 窗口关闭，其后请求视为背景流量
    return windows
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/windows.py server/tests/test_windows.py
git commit -m "feat: Transaction Window 切分（锚点+空闲关窗+上限）"
```

---

### Task 4: 状态信号提取（extract_state_signals）

**Files:**
- Create: `server/app/ingestion/signals.py`
- Test: `server/tests/test_signals.py`

**Interfaces:**
- Produces: `extract_state_signals(res_body: str | None) -> list[dict]`，返回 `[{"field": "data.status", "value": "APPROVED"}]`。只看顶层与一层嵌套（如 `data`）内 key 匹配 `^(status|state)$`（不区分大小写）且值为标量的字段。T5 消费。

- [ ] **Step 1: 写失败测试**

`server/tests/test_signals.py`：

```python
import json

from app.ingestion.signals import extract_state_signals


def test_top_level_status():
    body = json.dumps({"code": 200, "status": "APPROVED"})
    assert extract_state_signals(body) == [{"field": "status", "value": "APPROVED"}]


def test_nested_data_state():
    body = json.dumps({"data": {"state": "DRAFT", "id": 1}})
    assert extract_state_signals(body) == [{"field": "data.state", "value": "DRAFT"}]


def test_ignores_deep_and_non_scalar():
    body = json.dumps({"data": {"row": {"status": "x"}}, "state": {"nested": 1}})
    assert extract_state_signals(body) == []


def test_none_and_invalid():
    assert extract_state_signals(None) == []
    assert extract_state_signals("not json") == []
    assert extract_state_signals('{"status": 200}') == [{"field": "status", "value": 200}]
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_signals.py -v` → FAIL

- [ ] **Step 3: 实现**

`server/app/ingestion/signals.py`：

```python
import json
import re

STATE_KEY = re.compile(r"^(status|state)$", re.I)


def extract_state_signals(res_body: str | None) -> list[dict]:
    if not res_body:
        return []
    try:
        data = json.loads(res_body)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict] = []

    def walk(node: object, path: str) -> None:
        if not isinstance(node, dict) or path.count(".") >= 1:
            return
        for k, v in node.items():
            if STATE_KEY.match(k) and isinstance(v, (str, int, bool)):
                out.append({"field": f"{path}.{k}".lstrip("."), "value": v})
            elif isinstance(v, dict):
                walk(v, f"{path}.{k}")

    walk(data, "")
    return out
```

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/signals.py server/tests/test_signals.py
git commit -m "feat: 响应体状态信号提取（顶层+一层嵌套）"
```

---

### Task 5: process 服务 + 查询端点（raw_event → semantic_action）

**Files:**
- Create: `server/app/ingestion/process.py`、`server/app/api/ingest.py`
- Modify: `server/app/main.py`（挂载 ingest router）
- Test: `server/tests/test_process.py`

**Interfaces:**
- Consumes: T1 `split_url/templatize_path`、T3 `build_windows`、T4 `extract_state_signals`、T2 `SemanticAction`、既有 `RawEvent`/`get_db`。
- Produces:
  - `summarize_api(event: dict) -> dict`（`{seq, method, template, status, duration, params}`）；
  - `process_session(db: Session, session_id: str) -> dict`（返回 `{"windows": n}`；幂等：先删该 session 旧 semantic_action 再插新）；
  - `POST /api/v1/sessions/{session_id}/process` → `{"windows": n}`；404 session 不存在；
  - `GET /api/v1/sessions/{session_id}/semantic-actions` → `[SemanticAction...]`（按 window_seq 升序）。

- [ ] **Step 1: 写失败测试**

`server/tests/test_process.py`：

```python
async def _seed(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 900, "kind": "network",
         "payload": {"method": "GET", "url": "/codeBack/role/list", "status": 200,
                     "duration": 52, "reqBody": None, "resBody": '{"code":200}'}},
        {"seq": 2, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "duration": 74, "reqBody": "{}",
                     "resBody": '{"code":200,"status":"SUCCESS"}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    return sid


async def test_process_creates_semantic_actions(client):
    sid = await _seed(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    assert resp.json() == {"windows": 1}

    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["anchor_type"] == "click"
    assert row["target"]["label"] == "保存"
    assert [c["template"] for c in row["api_calls"]] == ["/codeBack/formConfig/saveFormConfig"]
    assert row["api_calls"][0]["method"] == "POST"
    assert row["state_signals"] == [{"api": "/codeBack/formConfig/saveFormConfig",
                                     "field": "status", "value": "SUCCESS"}]


async def test_process_idempotent(client):
    sid = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid}/process")
    await client.post(f"/api/v1/sessions/{sid}/process")  # 重算不重复
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1


async def test_process_404(client):
    resp = await client.post("/api/v1/sessions/nonexistent/process")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行确认失败**

Run: `cd server && uv run pytest tests/test_process.py -v`
Expected: FAIL（路由不存在）

- [ ] **Step 3: 实现**

`server/app/ingestion/process.py`：

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.signals import extract_state_signals
from app.ingestion.url_template import split_url, templatize_path
from app.ingestion.windows import build_windows
from app.models import RawEvent, SemanticAction


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
        select(RawEvent).where(RawEvent.session_id == session_id).order_by(RawEvent.seq)
    ).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind, "payload": r.payload or {}} for r in rows]
    windows = build_windows(events)

    db.query(SemanticAction).filter(SemanticAction.session_id == session_id).delete()
    for i, w in enumerate(windows):
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

`server/app/api/ingest.py`：

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion.process import process_session
from app.models import RecordingSession, SemanticAction

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sessions/{session_id}/process")
async def process(session_id: str, db: Session = Depends(get_db)) -> dict:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return process_session(db, session_id)


@router.get("/sessions/{session_id}/semantic-actions")
async def list_semantic_actions(session_id: str, db: Session = Depends(get_db)) -> list:
    if not db.get(RecordingSession, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db.query(SemanticAction).filter(
        SemanticAction.session_id == session_id
    ).order_by(SemanticAction.window_seq).all()
    return [
        {"window_seq": r.window_seq, "anchor_seq": r.anchor_seq,
         "anchor_type": r.anchor_type, "target": r.target,
         "api_calls": r.api_calls, "state_signals": r.state_signals}
        for r in rows
    ]
```

`server/app/main.py` 挂载（与既有 events router 并列）：

```python
from app.api import events, ingest
app.include_router(ingest.router, prefix=API_PREFIX)
```

注意：`app/api/ingest.py` 内的 `get_db` 与 `app/api/events.py` 的重复——本 Sprint 接受（Sprint 2 收敛到公共 deps）；不要在本任务顺手重构。

- [ ] **Step 4: 运行测试通过**

Run: `cd server && uv run pytest tests/ -v` → 全部 passed

- [ ] **Step 5: Commit**

```bash
git add server/app/ingestion/process.py server/app/api/ingest.py server/app/main.py server/tests/test_process.py
git commit -m "feat: session 处理管道与 semantic-action 查询端点"
```

---

### Task 6: 插件录制开关（popup + SW session 管理）

**Files:**
- Create: `extension/popup.html`、`extension/src/popup.ts`、`extension/src/background/session.ts`
- Modify: `extension/manifest.config.ts`（permissions 加 `"storage"`；加 `action: { default_popup: "popup.html" }`）
- Modify: `extension/src/background/uploader.ts`（注册 START/STOP/GET_STATE 消息，替代 CS 自建 session）

**Interfaces:**
- Consumes: T+0 既有 `AGENT_URL`、`putEvent`。
- Produces:
  - `session.ts` 导出 `startRecording(note: string): Promise<{id: string}>`、`stopRecording(): Promise<void>`、`getRecordingState(): Promise<{recording: boolean; sessionId: string | null; note: string}>`；storage 键 `sl_recording`/`sl_session`（chrome.storage.session）；
  - SW 消息协议：`{type: "START_RECORDING", note}` / `{type: "STOP_RECORDING"}` / `{type: "GET_STATE"}`，T7 的 capture.ts 依赖 `GET_STATE` 与 `sl_recording` 变更广播（storage.onChanged）。
- 验收（无浏览器）：vitest 全过 + build 成功 + dist 含 popup。

- [ ] **Step 1: session 管理实现**

`extension/src/background/session.ts`：

```typescript
import { AGENT_URL } from "../shared/types";

export interface RecordingState {
  recording: boolean;
  sessionId: string | null;
  note: string;
}

export async function startRecording(note: string): Promise<{ id: string }> {
  const res = await fetch(`${AGENT_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_system: "njmind", note }),
  });
  if (!res.ok) throw new Error(`create session failed: ${res.status}`);
  const session = await res.json();
  await chrome.storage.session.set({
    sl_recording: true,
    sl_session: session.session_id,
    sl_note: note,
  });
  return { id: session.session_id };
}

export async function stopRecording(): Promise<void> {
  await chrome.storage.session.remove(["sl_recording", "sl_session", "sl_note"]);
}

export async function getRecordingState(): Promise<RecordingState> {
  const st = await chrome.storage.session.get(["sl_recording", "sl_session", "sl_note"]);
  return {
    recording: st.sl_recording === true,
    sessionId: (st.sl_session as string) ?? null,
    note: (st.sl_note as string) ?? "",
  };
}
```

`extension/src/background/uploader.ts` 顶部消息区追加（与既有 events-pending 监听并列）：

```typescript
import { getRecordingState, startRecording, stopRecording } from "./session";

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "START_RECORDING") {
    startRecording(String(msg.note ?? "")).then(sendResponse).catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  if (msg?.type === "STOP_RECORDING") {
    stopRecording().then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg?.type === "GET_STATE") {
    getRecordingState().then(sendResponse);
    return true;
  }
});
```

注意：与既有 `events-pending` 监听并存时，两个 `onMessage.addListener` 都会被调用——`events-pending` 监听里对未知消息类型直接 return（不 return true）即可共存；如实现冲突，合并为单一监听器，行为不变。

- [ ] **Step 2: popup UI**

`extension/popup.html`：

```html
<!doctype html>
<html lang="zh">
  <head><meta charset="utf-8" /><style>body { width: 260px; font: 13px system-ui; padding: 10px; }</style></head>
  <body>
    <input id="note" placeholder="任务意图，如：创建订单" style="width: 100%; box-sizing: border-box;" />
    <div style="display: flex; gap: 8px; margin-top: 8px;">
      <button id="start" style="flex: 1;">开始录制</button>
      <button id="stop" style="flex: 1;">停止</button>
    </div>
    <div id="status" style="margin-top: 8px; color: #555;"></div>
    <script type="module" src="src/popup.ts"></script>
  </body>
</html>
```

`extension/src/popup.ts`：

```typescript
const note = document.getElementById("note") as HTMLInputElement;
const status = document.getElementById("status")!;

async function refresh(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  status.textContent = st?.recording
    ? `录制中：${st.note || "(未命名)"} / ${st.sessionId?.slice(0, 8)}`
    : "未录制";
}

document.getElementById("start")!.addEventListener("click", async () => {
  status.textContent = "创建会话…";
  const resp = await chrome.runtime.sendMessage({ type: "START_RECORDING", note: note.value });
  status.textContent = resp?.error ? `失败：${resp.error}` : "已开始录制";
  void refresh();
});

document.getElementById("stop")!.addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "STOP_RECORDING" });
  void refresh();
});

void refresh();
```

manifest 修改：`permissions: ["alarms", "storage"]`；新增 `action: { default_popup: "popup.html" }`。

- [ ] **Step 3: 构建与测试验证**

Run: `cd extension && npx vitest run && npm run build`
Expected: 测试全过；`dist/` 出现 `popup.html` 相关产物。浏览器实机验证推迟 T9。

- [ ] **Step 4: Commit**

```bash
git add extension/
git commit -m "feat: 录制开关（popup + SW 单 session 管理）"
```

---

### Task 7: capture.ts 改造（删自建 session、录制门控）

**Files:**
- Modify: `extension/src/content/capture.ts`

**Interfaces:**
- Consumes: T6 的 `sl_recording` storage 键与 `GET_STATE` 消息。
- Produces: capture 行为——录制关：不采集任何事件；录制开（含开录后页面才加载/或已开录的存量页面）：正常采集。事件 payload 不再携带有效 `__session_id`（统一置 `""`，由 T8 的 flush 回填）。删除 `ensureSession` 及其 fetch。

- [ ] **Step 1: 改造要点（整段替换 capture.ts 的状态与 emit 部分）**

```typescript
let recording = false;
const seq = 0; // 保留原 seq 计数器实现，不变

async function refreshState(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" }).catch(() => null);
  recording = st?.recording === true;
}
void refreshState();
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.sl_recording) {
    recording = changes.sl_recording.newValue === true;
  }
});

async function emit(kind: RawEvent["kind"], payload: Record<string, unknown>): Promise<void> {
  if (!recording) return;
  const event: RawEvent = {
    seq: nextSeq(), ts: Date.now(), kind,
    payload: { ...payload, __session_id: "" },
  };
  chrome.runtime.sendMessage({ type: EVENT_MSG, event }).catch(() => {});
}
```

其余改动：
1. 删除 `ensureSession` 函数与 `sessionId` 变量、删除对 `AGENT_URL` 的 import 使用；
2. `nextSeq()` 为原有 `seq` 自增逻辑封装（`let seq = 0; function nextSeq() { return seq++; }`）；
3. page-load navigation 事件改为在 `refreshState()` 完成后按 `recording` 判定再发（`void refreshState().then(() => { if (recording) void emit("navigation", {...}); })`）；
4. click/change/submit/message 监听器本身不变——`emit` 内部门控。
5. 注入 net-hook.js 与 message 桥保持不变（网络事件同样经 emit 门控）。

- [ ] **Step 2: 构建与测试验证**

Run: `cd extension && npx vitest run && npm run build && npx tsc --noEmit`
Expected: 13/13 全过、build 成功、tsc 无错。实机验证推迟 T9。

- [ ] **Step 3: Commit**

```bash
git add extension/src/content/capture.ts
git commit -m "feat: 采集受录制开关门控，session 交由 SW 统一管理"
```

---

### Task 8: flush 回填 session（断连不丢事件）

**Files:**
- Create: `extension/src/shared/assign-session.ts`、`extension/src/shared/assign-session.test.ts`
- Modify: `extension/src/background/uploader.ts`（flush 分组前回填）

**Interfaces:**
- Consumes: T6 `getRecordingState`；事件 payload 的 `__session_id`（可能为 `""`）。
- Produces: 纯函数 `assignSession(events: RawEvent[], sessionId: string | null): {assigned: RawEvent[]; deferred: RawEvent[]}`——有 sid 时空 `__session_id` 事件被回填该 sid 归入 assigned；sid 为 null 时，非空 sid 的归 assigned、空 sid 的归 deferred（留缓冲，不丢弃、不计重试）。

- [ ] **Step 1: 写失败测试**

`extension/src/shared/assign-session.test.ts`：

```typescript
import { assignSession } from "./assign-session";
import type { RawEvent } from "./types";

function ev(sid: string): RawEvent {
  return { seq: 1, ts: 0, kind: "action", payload: { __session_id: sid } };
}

describe("assignSession", () => {
  it("空 sid + 活跃 session → 回填", () => {
    const { assigned, deferred } = assignSession([ev("")], "abc");
    expect(assigned[0].payload.__session_id).toBe("abc");
    expect(deferred).toHaveLength(0);
  });

  it("空 sid + 无 session → 留缓冲", () => {
    const { assigned, deferred } = assignSession([ev("")], null);
    expect(assigned).toHaveLength(0);
    expect(deferred).toHaveLength(1);
  });

  it("已有 sid 的原样通过", () => {
    const { assigned } = assignSession([ev("xyz")], "abc");
    expect(assigned[0].payload.__session_id).toBe("xyz");
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `cd extension && npx vitest run src/shared/assign-session.test.ts` → FAIL

- [ ] **Step 3: 实现**

`extension/src/shared/assign-session.ts`：

```typescript
import type { RawEvent } from "./types";

export function assignSession(
  events: RawEvent[],
  sessionId: string | null,
): { assigned: RawEvent[]; deferred: RawEvent[] } {
  const assigned: RawEvent[] = [];
  const deferred: RawEvent[] = [];
  for (const e of events) {
    const sid = (e.payload.__session_id as string) ?? "";
    if (sid) {
      assigned.push(e);
    } else if (sessionId) {
      assigned.push({ ...e, payload: { ...e.payload, __session_id: sessionId } });
    } else {
      deferred.push(e);
    }
  }
  return { assigned, deferred };
}
```

- [ ] **Step 4: 运行测试通过**

Run: `cd extension && npx vitest run` → 全部 passed

- [ ] **Step 5: 接入 flush（uploader.ts）**

`doFlush` 中取事件后、分组前插入（deferred 的写回用 `putEvent`，不计入重试计数）：

```typescript
import { assignSession } from "../shared/assign-session";
import { getRecordingState } from "./session";

// doFlush 内，rows 取出后：
const state = await getRecordingState();
const { assigned, deferred } = assignSession(rows.map((r) => r.event), state.sessionId);
for (const e of deferred) await putEvent(e);
// 后续分组上报只遍历 assigned；bySession 为空则直接 return
```

以 uploader.ts 实际代码做等效最小接入（保持既有重试/防重入逻辑不动）。

- [ ] **Step 6: 构建验证 + Commit**

Run: `cd extension && npx vitest run && npm run build && npx tsc --noEmit`

```bash
git add extension/
git commit -m "feat: flush 前回填活跃 session，断连期事件不丢弃"
```

---

### Task 9: njmind 端到端验收（演示 1）

**Files:**
- Create: `demo/sprint1/README.md`、`demo/sprint1/semantic-actions-dump.txt`

**Interfaces:**
- Consumes: 全部前序任务。
- Produces: Sprint 1 验收证据，对应 spec §7 Sprint 1："semantic_action 正确关联 click ↔ POST ↔ 状态变化"。

- [ ] **Step 1: 启动两端并重载插件**

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
cd extension && npm run build   # Chrome 重新加载 dist
```

- [ ] **Step 2: 用户在 njmind 上操作（人工步骤）**

插件 popup → 填任务意图（如"保存表单配置"）→ 开始录制 → 在 njmind 表单页做一次含**输入+提交**的完整操作 → 等待 10s → popup 停止录制。

- [ ] **Step 3: 处理与验收（逐项确认）**

```bash
SID=$(sqlite3 server/skilllens.db "SELECT id FROM recording_session ORDER BY rowid DESC LIMIT 1")
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions/$SID/process
curl -s http://127.0.0.1:8710/api/v1/sessions/$SID/semantic-actions | python3 -m json.tool > demo/sprint1/semantic-actions-dump.txt
```

验收项：

1. 本 session 的 recording_session 只有一条（录制开关生效，不再每页一条）；
2. semantic-actions 中存在 `anchor_type=click/submit` 且 `target.label` 为按钮语义文本的窗口；
3. 该窗口 `api_calls` 含提交类 POST（模板化 URL，无具体 id）；
4. `state_signals` 至少一条（njmind 响应普遍含 code/status 类字段）；
5. 停止录制后再操作页面，raw_event 不新增（门控生效）；
6. 重跑 process 不产生重复行（幂等）。

- [ ] **Step 4: 记录证据并提交**

把 Step 3 各项结果写入 `demo/sprint1/README.md`。

```bash
git add demo/sprint1/
git commit -m "test: Sprint 1 njmind 端到端验收记录（演示 1：提交表单被切成语义窗口）"
git push
```

- [ ] **Step 5: Sprint 回顾**

对照 spec §12 防跑偏清单逐条自问（重点 #1 主线推进、#7 从 semantic_action 回溯 raw_event、#9 测试全绿）。

---

## Self-Review 记录

- **Spec 覆盖**：§4.2 Ingestion（URL 模板化→T1、Transaction Window→T3、关联→T5、状态→T4；脱敏按用户裁定移除并在 Global Constraints 记录）；§7 Sprint 1 验收（click↔POST↔状态）→T9 第 3/4 项；E2E 遗留加固（session 复用→T6、门控→T7、断连不丢→T8）。未覆盖（Sprint 2+）：自动触发 process、状态快照 Before/After、DOM 稳定信号。
- **占位符**：无 TBD；T7 Step 1 标注"整段替换"并给出完整目标代码结构，其余监听器明确"不变"。
- **类型一致性**：`RawEvent.payload.__session_id` 从 T7 起恒为 string（空串或 sid）；`assignSession` 签名与 T8 测试、flush 接入一致；`build_windows` 输入 dict 字段名与 T5 构造一致（seq/ts/kind/payload）；`summarize_api`/`process_session` 签名与 ingest.py 调用一致。
- **已知取舍**：ingest.py 与 events.py 的 get_db 重复（Sprint 2 收敛）；semantic_action 删旧插新不满足 append-only（Global Constraints 已裁定：仅 raw_event append-only）。



