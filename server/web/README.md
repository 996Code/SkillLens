# SkillLens Workbench（server/web）

只读 + 回放触发的工作台 Web 前端（Sprint 9 块 C，M1 出口「报告被团队评审」的载体）。
Vue 3 + Vite + TypeScript，无 UI 框架依赖（手写最小样式）。
生产同源部署：FastAPI 托管本目录构建产物 `dist/`，API 走相对路径零配置。

## 构建 / 开发 / 测试

```bash
# Node 24 便携版（本机路径）
export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"

npm install        # 首次
npm run build      # 构建到 dist/（server 启动时挂载；已挂载则新 dist 直接生效）
npm run dev        # 开发模式（vite dev server，代理见 vite.config.ts → 127.0.0.1:8710）
npm test           # vitest 单测（tests/*.spec.ts，jsdom 环境）
```

注意：dist 是静态文件，StaticFiles 每次请求读盘——server 运行中替换 dist 即生效；
但 `main.py` 在**启动时**判断 dist 存在性决定是否挂载，server 启动早于首次 build 时
不挂载（需重启 server 才会挂上）。

## 路由表

| 路径 | 视图 | 说明 |
| --- | --- | --- |
| `/` | — | 重定向 `/skills` |
| `/login` | `views/LoginView.vue` | 登录页（S21 块 S：唯一免认证页；成功存 token 跳 /skills） |
| `/skills` | `views/SkillsList.vue` | Skill 卡片网格（name/status/置信度/证据数/断言数/最近 run 状态点） |
| `/skills/:id` | `views/SkillDetail.vue` | 详情：概要 + 骨架步骤流 + 变量值域 + 断言表 + 窗口参数 + 最近回放；页脚「回放此 Skill」入口 |
| `/reports/:deltaId` | `views/DeltaReport.vue` | 四分类报告（expected/missing/unexpected/drift 分色卡 + 需求上下文 + id 查询框） |
| `/replay/:skillId` | `views/ReplayLaunch.vue` | 回放触发（Task 5）：overrides 编辑 + shadow/execute 模式门控 + 结果渲染 |
| `/audit` | `views/AuditView.vue` | 链路审计（S10.5 块 M）：会话列表→trace 下钻（窗口 kept/过滤原因→语义动作→对齐分桶→Skill→回放历史）+ 证据图过滤 + LLM 日志摘要 |
| `/timeline` | `views/TimelineView.vue` | 链路时间线（S32）：全流水线环节倒序时间轴（8 类型色点+过滤 chip）；LLM 项点击展开完整 prompt/response |

## API 依赖清单

| 端点 | 用途 | 消费方 |
| --- | --- | --- |
| `GET /api/v1/skills` | Skill 列表 | SkillsList |
| `GET /api/v1/skills/{id}/card` | Skill 聚合卡片（S9 新增，14 字段） | SkillsList / SkillDetail / ReplayLaunch |
| `GET /api/v1/reports/{id}` | 四分类报告行（S9 新增） | DeltaReport |
| `GET /api/v1/expected-deltas/{id}` | 需求上下文 | DeltaReport |
| `POST /api/v1/expected-deltas/{id}/observe` | 触发回放观测（同步返回 replay_run_id + replay_status；409 = shadow 未执行 / delta 未确认） | ReplayLaunch |
| `GET /api/v1/replay-runs/{id}` | run 明细（断言结果 attribution、plan 前后快照） | ReplayLaunch |
| `GET /api/v1/audit/sessions` | 审计会话列表（source/三计数，S10.5 新增） | AuditView |
| `GET /api/v1/audit/sessions/{sid}/trace` | 单会话链路下钻（窗口/语义动作/对齐/Skill/回放，S10.5 新增） | AuditView |
| `GET /api/v1/audit/evidence-edges` | 证据边列表（type/src_like 过滤，S10.5 新增） | AuditView |
| `GET /api/v1/audit/llm-logs` | LLM 调用日志（200 字摘要，完整走 DB，S10.5 新增） | AuditView |
| `GET /api/v1/audit/llm-logs/{id}` | 单条 LLM 调用完整 prompt/response（S32 新增，按需取用） | TimelineView |
| `GET /api/v1/timeline` | 全流水线环节时间线聚合（8 类型，S32 新增） | TimelineView |
| `GET /api/v1/replay-runs/{id}/step-screenshot` | 回放步骤截图出图（S33 新增，白名单防穿越） | TimelineView |

## 回放触发（C1 安全门控）

`/replay/:skillId` 表单两要素齐备才发 `confirm_side_effect=true`：

1. 模式单选：**shadow（默认）** / execute；
2. execute 时必须勾选「我已确认此操作有副作用并在旁观察」复选框，否则提交按钮禁用。

shadow 提交后 observe 返回 409（安全行为），页面友好提示这是预期内的拦截；
execute 成功后渲染 run 状态（pass 绿 / fail 红 / shadow 灰 / error 橙）、
断言明细表、失败归因、以及 plan.before_snapshot / after_snapshot 的 forms 差异对比
（只显有差异行，前 10 行）。

overrides 留空 = 沿用录制时采集值（空值前端剔除后不发送）。

## 只读边界

工作台不出现任何编辑 Skill / 断言 / Expected 的入口（宪法 §0.3 / 主计划块 C
Global Constraints）；执行类仅 observe 触发。

## S14 画布（/canvas）

| 端点 | 用途 |
| --- | --- |
| `GET/POST /api/v1/canvas` | 画布列表/保存（版本化新行，validate 不过 422） |
| `GET /api/v1/canvas/{id}` | 画布详情（含 DAG JSON） |
| `POST /api/v1/canvas/{id}/run` | 运行（同步返回 node_outputs；C1：confirm 编译期定格） |
| `GET /api/v1/canvas/{id}/runs` | 运行历史 |
| `GET /api/v1/canvas/runs/{run_id}` | run 详情（graph_name 前缀隔离） |
