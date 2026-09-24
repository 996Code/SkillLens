# Sprint 6 验收记录：MVP 收官（Docker 私有化 + 插件 UI + 压轴 E2E）

日期：2026-09-24。

## 验收标准（spec §7 Sprint 6）

> 端到端打磨 + 演示数据固化 + 私有化部署脚本（Docker Compose）；从装插件到出报告 ≤ 30 分钟，全程可复现。

## 交付

| 交付 | 内容 | 测试 |
|------|------|------|
| T1 CORS 配置化 | `ALLOWED_ORIGINS` env（默认 `*` 零行为变化，私有化收紧入口） | TDD 2 用例，pytest 93 |
| T2 Docker 化 | Dockerfile（uv + playwright chromium --with-deps，镜像 2.05GB）+ compose（env_file/volume/healthcheck）+ .dockerignore；**前置修复 alembic/env.py 读 DATABASE_URL**（原迁移写容器层与运行时 volume 库分裂） | 六项实测 6/6：build/health+迁移/接口/volume 持久化重启/镜像层无 .env/CORS 白名单 400·200 |
| T3 插件 UI | popup 现代化：320px 卡片、CSS 变量、**录制中红色脉冲点**、meta 会话信息、**Agent 连接状态点**；消息协议零改动 | build 全绿 + vitest 19/19 + 真实浏览器三态核验 3/3（computed style + 像素采样） |
| T4 部署文档+压轴 | deploy/README.md（部署/装插件/CORS 收紧/备份）+ 本验收 | 全链路计时实测 |

## 压轴 E2E（Docker 容器全链路）

时间线详见 `e2e-timeline.txt`。**T1-T0 = 139s ≤ 1800s**：

```
docker compose up（healthy）
→ 插件采集（带插件浏览器 CDP，11 事件落容器 volume DB）
→ process → align → induce（真实 LLM：SaveFormAndTableConfig learned）
→ assertions 4 → expected-delta（LLM draft）→ confirm 人工修订
→ observe：容器内 Playwright 回放 run 1 pass（8 观测项）
→ report：四分类 expected 3 / missing 1 / unexpected 5 / drift 0
```

要点：
- **采集→报告全程在容器化 server 上**（非本机进程），证明私有化部署形态可用
- 登录态经 override 挂载进容器（REPLAY_STORAGE_STATE=/data/njmind-state.json），实测后 override 已删——正式部署的挂载方式记入 deploy/README.md 可选段
- auto_record.py 的"本机 db 验证段"在容器场景按计划裁定忽略（R6），落库验证由容器内查询完成（11 事件确认）

## C1 核验

容器化不改变门控：observe 传 confirm_side_effect 才执行回放；skill 骨架含 POST → 未确认即 shadow。
（shadow 409 短路已有持久测试 test_observe_shadow_returns_409，Sprint 5 落地）

## 遗留（MVP 后）

- 镜像 2.05GB 偏大（chromium --with-deps 主导）；uv 工具镜像浮动 tag 建议 pin
- ghcr.io 首拉国内可能超时（deploy/README.md 已注明预拉方案）
- popup 三态截图存 /tmp/popup-{idle,recording}.png 供人工补看
