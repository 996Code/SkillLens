# SkillLens 私有化部署

## 前置
- Docker 20+ 与 Docker Compose v2+（本仓库实测：Docker 29.7.2 / Compose v5.3.1）
- 目标系统网络可达；LLM 网关（OpenAI 兼容协议）凭据
- Chrome 浏览器（装 Sensor 插件）
- 注意：Dockerfile 从 ghcr.io 拉 uv 工具镜像，国内网络首拉可能超时——失败重试或预拉
  `docker pull ghcr.io/astral-sh/uv:latest`

## 1. 起服务（二次起 ≤5 分钟）
```bash
cp .env.docker.example server/.env   # 填 LLM_* / NJMIND_* / ALLOWED_ORIGINS
docker compose up -d --build         # 首次构建约 5-10 分钟（含 chromium 依赖层，镜像 ~2GB）
curl http://127.0.0.1:8710/api/v1/health   # {"status":"ok"}
```
数据在 named volume `skilllens-data`（SQLite + 回放截图）；重启不丢。

## 2. 装插件
```bash
cd extension && npm run build
```
Chrome → `chrome://extensions` → 开发者模式 → 加载已解压的扩展程序 → 选 `extension/dist`。
插件直连 `127.0.0.1:8710`（compose 已映射），无需其他配置。popup 右下角有 Agent 连接状态点。

## 3. 全自动验证（可选，替代手动演示）
```bash
uv run python scripts/njmind_login.py /tmp/njmind-state-auto.json   # 刷新回放登录态
docker compose exec server sh -c 'echo $REPLAY_STORAGE_STATE'      # 容器内登录态路径（如挂载）
# 带插件自动采集：scripts/auto_record.py（SW 消息经 popup 页中转，CDP 操作被采集层捕获）
```
手动路径：插件 popup → 开始录制 → 目标系统操作 → 停止录制；然后依次调用
process → align → induce → assertions → expected-deltas（生成+confirm）→ observe → report。

## 4. CORS 收紧（私有化建议）
`server/.env` 设 `ALLOWED_ORIGINS=http://你的插件宿主`（逗号分隔多值）。
默认 `*` 仅为本地 POC 兼容。注意：设为空串等于全拒。

## 数据与备份
```bash
docker run --rm -v skilllens-data:/data -v $PWD:/backup alpine \
  tar czf /backup/skilllens-data.tgz /data
```
