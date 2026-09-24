# Sprint 6 MVP 收官 Implementation Plan（Docker 私有化 + 插件 UI + 压轴 E2E）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** server Docker Compose 私有化部署（从零起服务 ≤5 分钟）+ 插件 popup 现代化 UI + 压轴 E2E（docker compose 起的服务上，从装插件到出四分类报告 ≤30 分钟全程可复现）。

**Architecture:** ①server 单容器（python3.12-slim + uv + playwright chromium --with-deps），SQLite/artifacts 挂 volume，CORS 从 ALLOWED_ORIGINS env 读（默认 * 兼容现状）；②popup.html 重写为卡片式 UI（内联 CSS，无构建依赖），popup.ts 只加连接状态轮询，现有消息协议不动；③压轴 E2E 复用 Sprint 4.5 全自动闭环（auto_record.py + njmind_login.py），server 换成容器内实例。

**Tech Stack:** Docker 29.7.2 / Compose 5.3.1（已装）；无新 Python/JS 依赖。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md` §7 Sprint 6 行（端到端打磨 + 演示数据固化 + 私有化部署脚本 Docker Compose；验收：从装插件到出报告 ≤30 分钟）；§8 风险表"私有化前 CORS 收紧"。

## Global Constraints

- **C1/C2/C3 沿用**：容器内 server 行为与本地一致（shadow 门控、全落库、LLM 只生成/归因）。
- **安全红线**：`.env` 不进镜像层（`.dockerignore` 排除 + compose `env_file` 运行时注入）；镜像内无任何 key/凭据；compose 文件只引用变量名不写值。
- **CORS 收紧方式**：`ALLOWED_ORIGINS` env（逗号分隔，默认 `*` 完全兼容现状，测试不断）；私有化部署文档示例给收紧值。main.py 读 `app.config` 新增 `ALLOWED_ORIGINS`。
- **插件兼容**：AGENT_URL 是编译期常量（`http://127.0.0.1:8710/api/v1`）——容器映射端口 8710:8710 保持不变，插件零改动。
- **vitest 19 必须全绿**：popup.ts 现有逻辑（GET_STATE/START/STOP 消息）不改语义，只加渲染层。
- 测试基线：pytest 91；每任务完成后全量通过。
- 压轴验收口径：`docker compose down -v && docker compose up --build` 起服务 → auto_record 采集 → process/align/induce → expected-delta/observe/report → 四分类报告产出，全程计时 ≤30 分钟（首建镜像拉依赖除外，二次起服务 ≤5 分钟）。

---

### Task 1: CORS 可配置化（TDD）

**Files:**
- Modify: `server/app/config.py`（末尾加一行）
- Modify: `server/app/main.py:8-15`（读 config）
- Test: `server/tests/test_health.py`（追加用例）

**Interfaces:**
- Consumes: 既有 `load_dotenv()`（config.py 顶部）。
- Produces: `config.ALLOWED_ORIGINS: list[str]`（env `ALLOWED_ORIGINS` 逗号分隔，默认 `["*"]`）；main.py 中间件 `allow_origins=ALLOWED_ORIGINS`。

- [ ] **Step 1: 写失败测试**（追加到 `server/tests/test_health.py`）

```python
def test_cors_default_allows_all(client):
    r = client.options("/api/v1/sessions", headers={
        "Origin": "http://example.com",
        "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_cors_configurable(monkeypatch):
    import importlib
    import app.config as cfg
    import app.main as main_mod
    monkeypatch.setattr(cfg, "ALLOWED_ORIGINS", ["http://trusted.local"])
    main_mod.app.add_middleware.__self__.user_middleware.clear()  # 无法热重载中间件——见 Step 3 注
```

（Step 1 的第二个用例在 FastAPI 中间件不可热替换——**删掉它**，改为只测 config 层：）

```python
def test_cors_env_parsed(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.local, http://b.local")
    import importlib
    import app.config as cfg
    importlib.reload(cfg)
    assert cfg.ALLOWED_ORIGINS == ["http://a.local", "http://b.local"]
    monkeypatch.delenv("ALLOWED_ORIGINS")
    importlib.reload(cfg)
    assert cfg.ALLOWED_ORIGINS == ["*"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd server && uv run pytest tests/test_health.py -v`
Expected: FAIL（AttributeError: module 'app.config' has no attribute 'ALLOWED_ORIGINS'）

- [ ] **Step 3: 实现**

config.py 末尾追加：

```python
ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
```

main.py 替换 `allow_origins=["*"]` → `allow_origins=ALLOWED_ORIGINS`（import 行加 `from app.config import API_PREFIX, ALLOWED_ORIGINS`）；原 POC 注释更新为"CORS 由 ALLOWED_ORIGINS 配置（默认 * 兼容插件直连；私有化收紧见 deploy/README.md）"。

- [ ] **Step 4: 测试通过 + 全量 + 提交**

Run: `uv run pytest` → 93 passed
```bash
git add server/app/config.py server/app/main.py server/tests/test_health.py
git commit -m "feat(deploy): CORS 收紧为 ALLOWED_ORIGINS env 配置（默认 * 兼容）"
```

---

### Task 2: Docker 化 server（Dockerfile + compose + dockerignore）

**Files:**
- Create: `server/Dockerfile`
- Create: `server/.dockerignore`
- Create: `docker-compose.yml`（仓库根）
- Create: `.env.docker.example`（仓库根，占位键名）

**Interfaces:**
- Consumes: `server/pyproject.toml` + `uv.lock`（uv sync 锁定安装）；alembic 迁移（容器启动时 `alembic upgrade head`）。
- Produces: `skilllens-server` 镜像；compose 服务 `server`（8710:8710）；volumes：`skilllens-data:/data`（SQLite+artifacts，env `DATABASE_URL=sqlite:////data/skilllens.db`、`REPLAY_ARTIFACT_DIR=/data/artifacts`）。

- [ ] **Step 1: 写 `server/.dockerignore`**

```
.venv
__pycache__
*.db
.env
artifacts
tests
.pytest_cache
```

（tests 排除——镜像内不跑测试；.env 排除是安全红线。）

- [ ] **Step 2: 写 `server/Dockerfile`**

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN uv run playwright install chromium --with-deps

ENV HOST=0.0.0.0 PORT=8710
EXPOSE 8710

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host $HOST --port $PORT"]
```

（HOST=0.0.0.0——容器内必须监听全网卡才能映射；uvicorn 当前用 config.HOST 默认 127.0.0.1，env 已覆盖。）

- [ ] **Step 3: 写仓库根 `docker-compose.yml`**

```yaml
services:
  server:
    build: ./server
    ports:
      - "8710:8710"
    env_file:
      - server/.env
    environment:
      DATABASE_URL: sqlite:////data/skilllens.db
      REPLAY_ARTIFACT_DIR: /data/artifacts
    volumes:
      - skilllens-data:/data
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8710/api/v1/health')"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped

volumes:
  skilllens-data:
```

（env_file 指向 server/.env 运行时注入——LLM key/njmind 凭据不进镜像；文件缺省时 compose 报错提示，部署文档说明先复制 .env.example。）

- [ ] **Step 4: 写 `.env.docker.example`（仓库根，占位键名）**

```
# 复制为 server/.env 后按需填写；镜像不含任何密钥
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_MAX_TOKENS=
ALLOWED_ORIGINS=*
NJMIND_USER=
NJMIND_PASS=
NJMIND_LOGIN_URL=
```

- [ ] **Step 5: 构建验证（完善测试——五项实测）**

```bash
# ① build 成功
docker compose build 2>&1 | tail -3

# ② 起服务 + healthcheck 过 + 迁移已跑（/data 有库文件）
docker compose up -d && sleep 8
curl -s http://127.0.0.1:8710/api/v1/health        # {"status":"ok"}
docker compose ps                                  # STATUS (healthy)
docker compose exec server ls /data                # skilllens.db

# ③ 关键接口真实调通（容器内 DB）
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions \
  -H "Content-Type: application/json" -d '{"target_system":"njmind","note":"docker-smoke"}'
# 期望 200 带 session_id

# ④ volume 持久化：写入→重启→数据仍在
SID=$(curl -s -X POST http://127.0.0.1:8710/api/v1/sessions -H "Content-Type: application/json" \
  -d '{"note":"persist-check"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
docker compose restart && sleep 8
docker compose exec server python -c "
from app.db import SessionLocal
from app.models import RecordingSession
db = SessionLocal()
assert db.get(RecordingSession, '$SID'), 'volume 数据丢失'
print('persist ok:', '$SID'[:8])"

# ⑤ 安全：镜像层无 .env/密钥
docker compose exec server sh -c "ls -la /app/.env 2>&1; env | grep -c 'LLM_API_KEY=sk-' || true"
# 期望：.env 不存在；LLM_API_KEY 经 env_file 注入运行时（env 里有值是预期——验证的是"不在镜像文件层"）：
docker run --rm --entrypoint sh $(docker compose build 2>/dev/null | tail -1 | grep -o 'skilllens[^ ]*server' || echo skilllens-server) -c "ls /app/.env 2>&1" 2>/dev/null || \
docker run --rm --entrypoint sh $(docker images --format '{{.Repository}}:{{.Tag}}' | grep skilllens | head -1) -c "ls /app/.env 2>&1 | grep -q 'No such' && echo 'image clean: no .env'"

# ⑥ CORS 收紧生效验证（容器内设 ALLOWED_ORIGINS）
docker compose down
ALLOWED_ORIGINS=http://trusted.local docker compose up -d && sleep 8
curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS http://127.0.0.1:8710/api/v1/sessions \
  -H "Origin: http://evil.local" -H "Access-Control-Request-Method: POST"
# 期望 400（不在白名单）；Origin: http://trusted.local 则 200
curl -s -o /dev/null -w "%{http_code}\n" -X OPTIONS http://127.0.0.1:8710/api/v1/sessions \
  -H "Origin: http://trusted.local" -H "Access-Control-Request-Method: POST"
docker compose down
```

注：⑥ 的 ALLOWED_ORIGINS 经 compose environment 传递需临时加 `environment` 覆盖或用 `docker compose run -e`——实测时可直接 `docker compose exec` 内重启进程或写进临时 override 文件 `docker-compose.override.yml`（验证后删除）。

- [ ] **Step 6: 提交**

```bash
git add server/Dockerfile server/.dockerignore docker-compose.yml .env.docker.example
git commit -m "feat(deploy): server Docker 化（uv+playwright chromium，SQLite/artifacts volume，healthcheck）"
```

---

### Task 3: 插件 popup UI 现代化

**Files:**
- Modify: `extension/popup.html`（整页重写）
- Modify: `extension/src/popup.ts`（渲染层小改，消息协议不动）
- Test: `extension/src/popup.test.ts` 若存在则扩展；否则以构建+vitest 回归 + 浏览器实看为验证（见 Step 4）

**Interfaces:**
- Consumes: 既有消息协议 `GET_STATE / START_RECORDING{note} / STOP_RECORDING`（background/uploader.ts，**不改**）；`AGENT_URL`（连接探测 fetch，可选）。
- Produces: 新 DOM 结构（id 不变：`note/start/stop/status`——popup.ts 选择器兼容）；新增 `status-dot`（录制指示）与 `conn`（连接状态）节点。

- [ ] **Step 1: 重写 `popup.html`**

设计基调：320px 宽卡片、CSS 变量、system-ui 栈、录制中红色脉冲点、灰底按钮 hover 态。完整文件：

```html
<!doctype html>
<html lang="zh">
  <head>
    <meta charset="utf-8" />
    <style>
      :root {
        --bg: #f7f8fa;
        --card: #ffffff;
        --text: #1a2233;
        --muted: #6b7280;
        --line: #e5e7eb;
        --accent: #2563eb;
        --accent-hover: #1d4ed8;
        --danger: #dc2626;
        --ok: #16a34a;
        --radius: 12px;
      }
      * { box-sizing: border-box; margin: 0; }
      body {
        width: 320px;
        font: 13px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
        color: var(--text);
        background: var(--bg);
        padding: 12px;
      }
      .head {
        display: flex; align-items: center; gap: 8px;
        padding: 10px 12px; margin-bottom: 10px;
        background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
      }
      .logo {
        width: 22px; height: 22px; border-radius: 6px;
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        display: flex; align-items: center; justify-content: center;
        color: #fff; font-weight: 700; font-size: 11px;
      }
      .head .title { font-weight: 600; font-size: 13px; }
      .head .sub { font-size: 11px; color: var(--muted); }
      .dot {
        margin-left: auto; width: 8px; height: 8px; border-radius: 50%;
        background: #d1d5db; transition: background .2s;
      }
      .dot.rec { background: var(--danger); animation: pulse 1.2s ease-in-out infinite; }
      @keyframes pulse {
        0%, 100% { box-shadow: 0 0 0 0 rgba(220,38,38,.35); }
        50% { box-shadow: 0 0 0 6px rgba(220,38,38,0); }
      }
      .section {
        background: var(--card); border: 1px solid var(--line);
        border-radius: var(--radius); padding: 12px; margin-bottom: 10px;
      }
      .label { font-size: 11px; color: var(--muted); margin-bottom: 6px; }
      input#note {
        width: 100%; padding: 8px 10px; font: inherit;
        border: 1px solid var(--line); border-radius: 8px; outline: none;
        transition: border-color .15s;
      }
      input#note:focus { border-color: var(--accent); }
      .row { display: flex; gap: 8px; margin-top: 10px; }
      button {
        flex: 1; padding: 8px 0; font: inherit; font-weight: 500;
        border: none; border-radius: 8px; cursor: pointer;
        transition: background .15s, opacity .15s;
      }
      button#start { background: var(--accent); color: #fff; }
      button#start:hover { background: var(--accent-hover); }
      button#stop {
        background: #eef2f7; color: var(--text);
      }
      button#stop:hover { background: #e2e8f0; }
      button:disabled { opacity: .5; cursor: not-allowed; }
      .status {
        display: flex; align-items: center; gap: 6px;
        font-size: 12px; color: var(--muted); padding: 2px 4px;
      }
      .status .sdot { width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; }
      .status.rec .sdot { background: var(--danger); }
      .status.ok .sdot { background: var(--ok); }
      #status { word-break: break-all; }
      .conn {
        display: flex; align-items: center; gap: 6px;
        font-size: 11px; color: var(--muted); padding: 0 4px 2px;
      }
      .conn .cdot { width: 6px; height: 6px; border-radius: 50%; background: #d1d5db; }
      .conn.ok .cdot { background: var(--ok); }
      .conn.err .cdot { background: var(--danger); }
      .meta {
        font-size: 11px; color: var(--muted); margin-top: 4px; padding: 0 4px;
      }
    </style>
  </head>
  <body>
    <div class="head">
      <div class="logo">SL</div>
      <div>
        <div class="title">SkillLens Sensor</div>
        <div class="sub">操作观察 · 技能学习</div>
      </div>
      <div class="dot" id="status-dot"></div>
    </div>

    <div class="section">
      <div class="label">任务意图（录制备注）</div>
      <input id="note" placeholder="如：创建订单 / 保存表单配置" />
      <div class="row">
        <button id="start">开始录制</button>
        <button id="stop">停止</button>
      </div>
    </div>

    <div class="status" id="status-wrap">
      <span class="sdot"></span><span id="status">未录制</span>
    </div>
    <div class="meta" id="meta"></div>
    <div class="conn" id="conn">
      <span class="cdot"></span><span id="conn-text">连接本地 Agent…</span>
    </div>

    <script type="module" src="src/popup.ts"></script>
  </body>
</html>
```

- [ ] **Step 2: `popup.ts` 渲染层适配（协议不动）**

保持 `note/start/stop/status` 四个 id 的引用不变；追加状态联动（完整文件）：

```ts
// 标记为 ES module：避免顶层 const 与 DOM 全局冲突
export {};

const note = document.getElementById("note") as HTMLInputElement;
const status = document.getElementById("status")!;
const wrap = document.getElementById("status-wrap")!;
const dot = document.getElementById("status-dot")!;
const meta = document.getElementById("meta")!;
const conn = document.getElementById("conn")!;
const connText = document.getElementById("conn-text")!;

function render(recording: boolean, noteText: string, sessionId: string | null): void {
  status.textContent = recording ? "录制中" : "未录制";
  wrap.classList.toggle("rec", recording);
  dot.classList.toggle("rec", recording);
  meta.textContent = recording
    ? `${noteText || "(未命名)"} · ${sessionId ? sessionId.slice(0, 8) : ""}`
    : "";
}

async function refresh(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  render(!!st?.recording, st?.note ?? "", st?.sessionId ?? null);
}

// 连接探测：直连 Agent health（失败不阻塞录制流程，只显红点）
async function probe(): Promise<void> {
  try {
    const { AGENT_URL } = await import("./shared/types");
    const res = await fetch(`${AGENT_URL}/health`);
    connText.textContent = res.ok ? "Agent 已连接" : "Agent 异常";
    conn.classList.toggle("ok", res.ok);
    conn.classList.toggle("err", !res.ok);
  } catch {
    connText.textContent = "Agent 未连接（检查 8710）";
    conn.classList.add("err");
  }
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
void probe();
```

- [ ] **Step 3: 构建 + vitest 全绿**

```bash
cd extension && npm run build 2>&1 | tail -3   # 无错误
npm test 2>&1 | grep -E "Test Files|Tests "    # 19 passed（协议未动，零回归）
```

- [ ] **Step 4: 浏览器实看（完善测试——UI 必须真看，不只编译过）**

用带插件的 Playwright（复用 scripts/auto_record.py 的启动方式）打开 popup 截图验证三态：

```python
# /tmp/popup_screenshot.py
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

EXT = "/Users/xiaotaotao/cyble-code/SkillLens/extension/dist"

async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            "/tmp/skilllens-ext-profile", headless=False,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        sw = next(w for w in ctx.service_workers if "service-worker-loader" in w.url)
        ext_id = sw.url.split("/")[2]
        page = await ctx.new_page()
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        await page.wait_for_timeout(1200)
        await page.screenshot(path="/tmp/popup-idle.png")
        # 触发录制态：经 popup 页发消息（SW 自发自收不触发，必须页面上下文）
        await page.evaluate(
            '() => chrome.runtime.sendMessage({type: "START_RECORDING", note: "UI 验证"}))' if False else
            '() => chrome.runtime.sendMessage({type: "START_RECORDING", note: "UI 验证"})')
        await page.reload()
        await page.wait_for_timeout(1200)
        await page.screenshot(path="/tmp/popup-recording.png")
        await page.evaluate('() => chrome.runtime.sendMessage({type: "STOP_RECORDING"})')
        await ctx.close()

asyncio.run(main())
```

检查点（读图）：idle 态灰点/灰文案；recording 态红脉冲点 + "录制中" + meta 显示备注与 sid 前 8 位；Agent 连接绿点（server 在跑时）。任一不符即修 CSS。

- [ ] **Step 5: 提交**

```bash
git add extension/popup.html extension/src/popup.ts
git commit -m "feat(ui): popup 现代化——卡片布局/录制脉冲指示/Agent 连接状态（协议零改动）"
```

---

### Task 4: 部署文档 + 压轴 E2E（≤30 分钟实测）

**Files:**
- Create: `deploy/README.md`
- Create: `demo/sprint6/README.md`、`demo/sprint6/e2e-timeline.txt`

**Interfaces:**
- Consumes: Task 1-3 全部；`scripts/njmind_login.py` + `scripts/auto_record.py`（全自动闭环）；`server/.env`（env_file 注入容器）。
- Produces: spec §7 Sprint 6 验收——从装插件到出报告 ≤30 分钟全程可复现 + 部署文档。

- [ ] **Step 1: 写 `deploy/README.md`**

结构（内容完整写出，不占位）：

```markdown
# SkillLens 私有化部署

## 前置
- Docker 20+ 与 Docker Compose v2+
- 目标系统可达；LLM 网关（OpenAI 兼容）凭据
- Chrome 浏览器（装 Sensor 插件）

## 1. 起服务
cp .env.docker.example server/.env   # 填 LLM_* / NJMIND_* / ALLOWED_ORIGINS
docker compose up -d --build
curl http://127.0.0.1:8710/api/v1/health   # {"status":"ok"}

## 2. 装插件
cd extension && npm run build
Chrome → chrome://extensions → 开发者模式 → 加载已解压的扩展程序 → 选 extension/dist

## 3. 验证闭环（全自动脚本或手动）
# 自动：uv run python scripts/njmind_login.py /tmp/njmind-state-auto.json
#       REPLAY_STORAGE_STATE=/tmp/njmind-state-auto.json 已在容器 env 时跳过本机注入
# 手动：插件 popup → 开始录制 → 在目标系统操作 → 停止录制
# 然后依次：process → align → induce → assertions → expected-deltas → observe → report

## 4. CORS 收紧（私有化建议）
server/.env 设 ALLOWED_ORIGINS=http://your-chrome-host（默认 * 仅为本地 POC）

## 数据与备份
- SQLite 与回放截图在 named volume skilllens-data（/data）
- 备份：docker run --rm -v skilllens-data:/data -v $PWD:/backup alpine tar czf /backup/skilllens-data.tgz /data
```

- [ ] **Step 2: 压轴 E2E 计时实测（控制器执行）**

```bash
# T0 计时开始（含 docker compose down -v 清零）
docker compose down -v 2>/dev/null; T0=$(date +%s)
docker compose up -d --build && sleep 10
# 起服务后：全自动闭环
cd server && uv run python ../scripts/njmind_login.py /tmp/njmind-state-auto.json
# 插件路径：auto_record（带插件浏览器 → 开录 → 操作 → 停录 → 落库）
uv run python ../scripts/auto_record.py --note sprint6-final
SID=$(sqlite3 /dev/null "" 2>/dev/null; docker compose exec server python -c "
from app.db import SessionLocal; from app.models import RecordingSession
db=SessionLocal(); print(db.query(RecordingSession).order_by(RecordingSession.started_at.desc()).first().id)")
# 注意：auto_record.py 的落库验证段直连本机 skilllens.db——容器场景数据在 volume，
# 验证改用 API/容器内 python（见 Step 3 记录），脚本本身不改（本机模式仍可用）
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions/$SID/process
curl -s -X POST http://127.0.0.1:8710/api/v1/align -H "Content-Type: application/json" -d "{\"session_ids\":[\"$SID\",\"$SID\"]}"
# induce（真实 LLM）→ assertions → expected-deltas → observe → report（同 Sprint 5 流程）
T1=$(date +%s); echo "总耗时: $((T1-T0))s（需 ≤1800）"
```

- [ ] **Step 3: 验收记录 demo/sprint6/**

README.md 记录：时间线（各阶段耗时）、四分类报告产出、C1 核验、UI 截图（popup-idle/recording.png 引用）。e2e-timeline.txt 存原始计时与各接口响应。

```bash
git add deploy/ demo/sprint6/ && git commit -m "docs(deploy): 私有化部署指南 + Sprint 6 压轴 E2E 验收（≤30 分钟闭环）"
```

- [ ] **Step 4: Sprint 回顾（MVP 收官检查）**

对照 spec §9 成功标准（8 条 + 第 8 条四分类真实构造）逐条核对；§12 防跑偏清单全查；更新 demo 索引（demo/README.md 若无则建，列 sprint0-6 各演示入口）。

---

## Self-Review 记录

- **Spec 覆盖**：§7 Sprint 6 三交付——端到端打磨（T4 压轴+demo 索引）、演示数据固化（T4 时间线+volume 持久化验证 T2⑤）、私有化部署脚本 Docker Compose（T1 CORS+T2 容器+T4 文档）；验收"≤30 分钟可复现"（T4 Step 2 计时）。§8 风险表"CORS 收紧"（T1，env 化）。
- **完善测试落实**（用户 2026-09-24 叮嘱）：T1 TDD 2 用例（默认 * + env 解析 + 真实 OPTIONS 预检）；T2 六项实测（build/health+迁移/关键接口/volume 持久化重启/镜像无 .env/CORS 容器内生效）；T3 构建全绿 + vitest 19 零回归 + 浏览器三态截图实看；T4 全链路计时 + 四分类产出核验。
- **占位符**：无 TBD；T4 Step 2 的 sqlite3 直连行已标注"验证改用容器内"并说明。
- **类型一致性**：popup.ts 的 id 引用（note/start/stop/status）与 HTML 一致；新增 status-wrap/status-dot/meta/conn/conn-text 与 render()/probe() 一致；AGENT_URL import 与 shared/types.ts 导出一致；compose 端口/env 名与 config.py（HOST/PORT/DATABASE_URL/REPLAY_ARTIFACT_DIR 读 env）一致。
- **已知取舍**：auto_record.py 落库验证段是本机 sqlite 直查，容器场景在 T4 用容器内命令替代（脚本不改，本机模式保留）；popup 连接探测失败不阻塞录制（SW 上报路径不依赖 popup）。
