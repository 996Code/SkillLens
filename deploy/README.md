# SkillLens 私有化部署向导

> 按步骤执行，每步有预期输出；失败查文末排查表。全程约 15 分钟（首建 5-10 分钟）。

## 前置检查

| # | 检查 | 命令 | 预期 |
|---|---|---|---|
| 0.1 | Docker | `docker --version` | ≥ 20 |
| 0.2 | Compose | `docker compose version` | v2+ |
| 0.3 | 网络 | 目标系统与 LLM 网关可达 | — |

国内网络注意：Dockerfile 从 ghcr.io 拉 uv 工具镜像可能超时——失败重试或预拉
`docker pull ghcr.io/astral-sh/uv:latest`。

## 步骤 1：配置凭据

```bash
cp .env.docker.example server/.env
```

编辑 `server/.env`，填入：

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_MAX_TOKENS` | OpenAI 兼容网关凭据（客户自带 Key） |
| `NJMIND_USER` / `NJMIND_PASS` / `NJMIND_LOGIN_URL` | 目标系统凭据（录制/回放登录态） |
| `ALLOWED_ORIGINS` | 插件宿主源（见步骤 4） |
| `PII_PATTERNS` | 可选：追加脱敏字段名正则，逗号分隔，如 `idcard,phone` |

**预期**：文件保存后无输出。凭据永不入镜像/仓库（.env 已 gitignore）。

## 步骤 2：起服务

```bash
docker compose up -d --build
curl http://127.0.0.1:8710/api/v1/health
```

**预期**：`{"status":"ok"}`（首次构建 5-10 分钟，镜像 ~2GB 含 chromium）。
数据在 named volume `skilllens-data`（SQLite + 回放截图），重启不丢。

## 步骤 2.5：建号（S21 起工作台需要登录）

工作台 API 默认要求 Bearer token（插件上报通道豁免）。空库无账号，先建 admin：

```bash
docker compose exec server python -m app.create_user <用户名> <密码> admin
# 本地开发：cd server && uv run python -m app.create_user <用户名> <密码> admin
```

角色三级：`admin`（建号/全权）> `reviewer`（可评审）> `viewer`（只读）。
admin 登录工作台后也可经 `POST /api/v1/auth/users` 建号。

## 步骤 3：装插件

```bash
cd extension && npm run build
```

Chrome → `chrome://extensions` → 开发发者模式 → 加载已解压的扩展程序 → 选 `extension/dist`。
插件直连 `127.0.0.1:8710`（compose 已映射）。popup 右下角 Agent 连接状态点应为绿色。

**预期**：popup 打开显示"Agent 已连接"。

## 步骤 4：CORS 收紧（私有化必做）

`server/.env` 设 `ALLOWED_ORIGINS=http://你的插件宿主`（逗号分隔多值），然后：

```bash
docker compose up -d   # 重建容器加载新 env
```

**预期**：非白名单 Origin 请求返回 403/被拒；插件正常工作。
默认 `*` 仅为本地 POC 兼容。注意：空串等于全拒。

## 步骤 5：验证闭环（全自动，可选）

```bash
cd server && uv run python ../scripts/njmind_login.py /tmp/njmind-state-auto.json
```

容器内回放需要登录态，挂载方式（compose override）：

```yaml
services:
  server:
    volumes:
      - /tmp/njmind-state-auto.json:/data/njmind-state.json:ro
    environment:
      REPLAY_STORAGE_STATE: /data/njmind-state.json
```

**预期**：state 文件 ~220KB；空文件会令容器内 Playwright 抛 JSONDecodeError（重新登录刷新）。
手动路径：插件 popup → 开始录制 → 操作 → 停止；然后 process → align → induce →
assertions → expected-deltas（生成+confirm）→ observe → report。

## 步骤 6：备份（日常运维）

```bash
docker run --rm -v skilllens_skilllens-data:/data -v $PWD:/backup alpine \
  tar czf /backup/skilllens-data.tgz /data
tar tzf skilllens-data.tgz | head   # 抽查非空
```

**预期**：tar 列表含 `data/skilllens.db` 等文件。
（volume 实名带 compose 项目前缀，`docker volume ls | grep skilllens` 确认。）
**Git Bash（Windows）注意**：MSYS 会把容器内路径 `/backup/...` 改写成
Windows 路径导致 `can't open` —— 命令前加 `MSYS_NO_PATHCONV=1`，且
`-v` 挂载用显式 Windows 路径（如 `-v "D:/path:/backup"`）。

## 步骤 7：恢复（灾难恢复，已实测演练）

```bash
docker compose down                    # 停服务（volume 保留）
docker volume rm skilllens_skilllens-data   # 删旧卷
docker volume create skilllens_skilllens-data
docker run --rm -v skilllens_skilllens-data:/data -v $PWD:/backup alpine \
  sh -c "cd / && tar xzf /backup/skilllens-data.tgz"
docker compose up -d
curl http://127.0.0.1:8710/api/v1/health   # {"status":"ok"}
curl http://127.0.0.1:8710/api/v1/skills    # 数据回来
```

**预期**：health ok + skills 列表与备份前一致（2026-09-25 本机实测演练通过）。

## 故障排查

| 症状 | 原因 | 处置 |
|---|---|---|
| 构建时 ghcr.io 超时 | 国内网络 | 预拉 `docker pull ghcr.io/astral-sh/uv:latest` 后重试 |
| health 404 | 迁移未跑 | `docker compose exec server uv run alembic upgrade head` |
| 插件连不上 | CORS/端口 | 查步骤 4；确认 8710 映射 |
| 回放 JSONDecodeError | state 文件空/过期 | 重新跑 njmind_login.py 刷新 |
| 恢复后数据空 | tar 路径错 | 恢复命令必须 `cd /` 后解包（保持 data/ 前缀） |
