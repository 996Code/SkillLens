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
npm test           # vitest 单测（tests/*.spec.ts，jsdom 环境；当前 78 用例全绿）
```

注意：dist 是静态文件，StaticFiles 每次请求读盘——server 运行中替换 dist 即生效；
但 `main.py` 在**启动时**判断 dist 存在性决定是否挂载，server 启动早于首次 build 时
不挂载（需重启 server 才会挂上）。

## 共享模块与开发约定（三轮评审沉淀）

- `src/run-format.ts`：断言摘要/时间格式化的**单一来源**（`assertExpect`/`fmtTime` 等）——
  视图不得再各写一份 payload 摘要（SkillGraphView 的 `payloadSummary` 双源漂移已删，行为由
  `tests/run-format.spec.ts` 定版）。
- `src/system-group.ts`：系统分组排序（`SYSTEM_ORDER`）与配色（`SYSTEM_COLORS`/`systemColor()`，
  未列系统回退默认灰）——GraphOverview 圆点等处一律经它取色，**不要再写 CSS 属性选择器**
  （曾因短名 vs 全名失配全成死样式）。`tests/system-group.spec.ts` 定版。
- `src/api.ts` 的 `send<T>()`/`jsonInit()`：写请求统一出口（detail 提取 + 状态行回退文案与
  历史逐字一致）——新增 POST 不再手抄 15 行样板。
- **竞态守卫（seq 单调递增）**已是规范模式，落地于 AuditView/SkillGraphView/TimelineView/
  FlowGraph/ShotGallery/CanvasView 六处：异步结果回来先比对 seq，过期即丢弃并 revoke blob。
  新写"选择→异步加载"视图必须照此办理。
- 路由参数变化须 `watch(route.params.*)` 重载（ReplayLaunch/ReplayRunView 曾缺——组件复用
  时展示旧数据）。

## 路由表

| 路径 | 视图 | 说明 |
| --- | --- | --- |
| `/` | — | 重定向 `/graph` |
| `/login` | `views/LoginView.vue` | 登录页（S21 块 S：唯一免认证页；成功存 token 跳 /graph） |
| `/graph` | `views/graph/GraphWorkspace.vue` + `GraphOverview.vue` | 图工作台壳（S39-S42：左树=唯一导航，分组折叠+搜索）+ 系统总览（流水线卡片 + 按系统分组的流程入口） |
| `/graph/skill/:skillId` | `views/graph/SkillGraphView.vue` | 流程详情（S42 合并旧 SkillDetail）：流程图 + 断言表 + 变量值域 + 自愈提案 + 视觉回归 + 导出/回放入口 |
| `/graph/suites` | `views/SuitesView.vue` | 测试套件（S37-3）：组合操作流程 → 一键执行 → 汇总 + 执行历史 |
| `/graph/timeline` | `views/TimelineView.vue` | 测试活动时间线（S37-2 重构）：test_run/recording 两类；include_internal 开发者视角 |
| `/graph/run/:runId` | `views/ReplayRunView.vue` | 回放 run 详情（S34）：状态/flaky/耗时 + 步骤表 + 截图墙（点击放大）+ 断言明细 + 归因 + 快照对比 |
| `/graph/replay/:skillId` | `views/ReplayLaunch.vue` | 回放触发（Task 5）：overrides 编辑 + shadow/execute 模式门控 + 结果渲染 |
| `/graph/reports/:deltaId` | `views/DeltaReport.vue` | 四分类报告（expected/missing/unexpected/drift 分色卡 + 需求上下文 + id 查询框） |
| `/graph/audit` | `views/AuditView.vue` | 链路审计（S10.5 块 M）：会话列表→trace 下钻（窗口 kept/过滤原因→语义动作→对齐分桶→Skill→回放历史）+ 证据图过滤 + LLM 日志摘要 |
| `/graph/canvas` | `views/CanvasView.vue` | 编排画布（S14） |
| `/graph/adapters` | `views/graph/AdaptersView.vue` | 系统接入清单（AF6+平台化）：YAML 查看/校验/保存 + 画像指纹贴 HTML 生成草稿（P2） |
| `/graph/reviews-portal` | `views/ReviewPortal.vue` | 评审门户（S15） |

旧路径（`/skills/:id`、`/replay-runs/:runId` 等 11 条）全部重定向到对应 `/graph/*` 新路径（不丢深链）。

## API 依赖清单

| 端点 | 用途 | 消费方 |
| --- | --- | --- |
| `GET /api/v1/skills` | Skill 列表（含 system 目标系统） | GraphWorkspace 左树 / GraphOverview / SuitesView |
| `GET /api/v1/skills/{id}/card` | Skill 聚合卡片（S9 新增，14 字段） | SkillGraphView / ReplayLaunch |
| `GET /api/v1/reports/{id}` | 四分类报告行（S9 新增） | DeltaReport |
| `GET /api/v1/expected-deltas/{id}` | 需求上下文 | DeltaReport |
| `POST /api/v1/expected-deltas/{id}/observe` | 触发回放观测（同步返回 replay_run_id + replay_status；409 = shadow 未执行 / delta 未确认） | ReplayLaunch |
| `GET /api/v1/replay-runs/{id}` | run 明细（断言结果 attribution、plan 前后快照；S34 补 duration/flaky/created_at） | ReplayLaunch / ReplayRunView |
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
