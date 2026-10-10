# SkillLens 项目导览（PROJECT-GUIDE）

> 一份文档讲清整个项目：是什么 → 在哪 → 怎么跑 → 怎么继续开发。
> 人类新成员与 AI 接手者均从本文起步。**文末附 AI 学习提示词。**

## 1. 项目是什么

**SkillLens** = AI 软件学习 + 变更智能。一句话：让 AI 观察真实用户如何使用你的
内部系统，自动归纳出可回放的"Skill"（操作能力）；每次系统发版后，自动判断
**应该改变的有没有改变、不应该改变的有没有被破坏**，产出四分类变更报告。

核心闭环：
```
Chrome 插件采集（UI+Network+State 证据，影子模式）
  → 语义动作 → 窗口对齐 → Skill 归纳（LLM 命名 + 确定性回查防幻觉）
  → 断言生成（6 层证据）→ 语义定位回放（C1 影子门控）
  → Expected Delta（需求预期，人工确认）vs Observed Delta（回放实测）
  → 四分类报告：Expected / Missing / Unexpected / Drift
  → 夜间定向回归（画布编排）→ 晨间评审门户 → Webhook 通知
```

三条硬性约束（产品宪法，零例外）：
- **C1 影子模式**：destructive 操作未确认绝不执行（编译期定格 + DB 不变量双保险）
- **C2 真实流量分轨**：demo | real_traffic 标记贯穿
- **C3 全链路落库**：含失败的 LLM 调用，异常摘要 URL 脱敏

LLM 边界纪律：**LLM 只做命名/结构化/归因/提案，一切判定都是确定性的**（回查、
断言评估、四分类、视觉比对、性能漂移、自愈验证全部纯函数可复现）。

## 2. 仓库结构（目录地图）

```
SkillLens/
├── AGENTS.md                    ← 操作宪法（所有贡献者/子代理必读必守）
├── PROJECT-GUIDE.md             ← 本文
├── README.md                   ← 项目门面（快速开始+能力表）
├── docker-compose.yml          ← 私有化部署入口
│
├── server/                      ← 后端（FastAPI + SQLAlchemy + SQLite + Playwright）
│   ├── README.md               ← 后端导览（模块地图+数据流+红线速查）
│   ├── app/
│   │   ├── main.py             ← 应用装配（路由挂载+SPA 托管+认证守卫）
│   │   ├── config.py           ← 全部 env 配置（阈值/开关集中地）
│   │   ├── models.py           ← 全部 ORM 模型（25+ 表）
│   │   ├── auth.py             ← 密码/会话纯函数（pbkdf2+token 哈希）
│   │   ├── create_user.py      ← 建号引导脚本
│   │   ├── schemas.py          ← Pydantic 请求体
│   │   ├── api/                ← 21 个路由模块（每个文件头有契约注释）
│   │   │   ├── auth.py         ←  登录/登出/me/建号（S21）
│   │   │   ├── events.py       ←  插件上报通道（认证豁免）
│   │   │   ├── ingest.py       ←  process/align/induce（学习管道入口）
│   │   │   ├── replay.py       ←  单/批回放
│   │   │   ├── change.py       ←  expected-deltas 四步闭环+报告生成
│   │   │   ├── reports.py      ←  报告读取+/perf 性能上下文
│   │   │   ├── visual.py       ←  视觉基线信息/重置/图片
│   │   │   ├── locate_proposals.py ← 自愈提案列表/否决/晋升
│   │   │   ├── export.py       ←  Playwright 脚本导出（skill+flow）
│   │   │   └── ...             ←  audit/baseline/canvas/cards/dev_plans/
│   │   │                          discoveries/flows/generic_skills/
│   │   │                          health/impact/llm_skills/reviews
│   │   ├── replay/             ← 回放引擎核心
│   │   │   ├── runner.py       ←  执行编排（_attempt 重试+flaky+自愈挂钩）
│   │   │   ├── locate.py       ←  语义定位（role→text→placeholder→label→id）
│   │   │   ├── plan.py         ←  骨架→回放计划编译（healed label 优先）
│   │   │   ├── assert_eval.py  ←  断言评估（确定性）
│   │   │   ├── page_snapshot.py←  回放侧 UI 快照（与插件同 schema）
│   │   │   ├── visual.py       ←  视觉比对（dHash+像素占比，S22）
│   │   │   ├── repair.py       ←  定位修复提案（LLM 提案+locate 实测验证）
│   │   │   ├── exporter.py     ←  Playwright 脚本导出器（S25/S26b）
│   │   │   └── flow_runner.py  ←  流程合成执行器
│   │   ├── change/             ← 四分类域（classify 纯函数/perf 性能基线）
│   │   ├── learning/           ← 学习域（skill 归纳/generic 通用层/impact/
│   │   │                          synthesis 流程合成/evidence 证据图）
│   │   ├── ingestion/          ← 摄取域（process/alignment/windows/
│   │   │                          noise_filter/variables/url_template）
│   │   ├── agents/             ← 夜间运行时（runtime/canvas/scheduler/
│   │   │                          dev_executor 夜间开发）
│   │   ├── llm/                ← 网关（complete() 统一出口+C3 落库）
│   │   └── integrations/       ← webhook 通知（wecom/dingtalk/slack/generic）
│   ├── alembic/versions/       ← 全部迁移（文件名即主题）
│   └── web/                    ← 工作台前端（Vue3+TS+Vite）
│       ├── src/views/          ←  8 页面（登录/技能列表/详情/报告/回放/
│       │                           审计/画布/评审）
│       ├── src/api.ts          ←  全部 API 封装（authedFetch 统一认证出口）
│       └── tests/              ←  vitest（11 文件 50 用例）
│
├── extension/                   ← Chrome MV3 插件（TS）
│   ├── src/content/             ←  采集（capture/snapshot，与 server 同 schema）
│   ├── src/background/          ←  会话管理/上传
│   ├── src/shared/              ←  describe-element/redact/input-key（红线同源）
│   └── tests/                   ←  vitest（31 用例）
│
├── deploy/README.md             ← 私有化部署向导（7 步+排查表）
├── scripts/                     ← 实操脚本（live_browser 常驻浏览器/auto_record
│                                   自动采集/njmind_login/webhook_receiver/
│                                   s2X_screenshots 各 Sprint 截图）
├── demo/sprint0 ~ sprint27/     ← 每 Sprint 验收记录+截图+用户测试报告
└── docs/
    ├── COLLABORATION-CHARTER.md   ← 协作宪章（用户全部要求汇总，传承文档）
    ├── specs/                      ← 产品宪法 + 交付主计划（唯一范围基准）
    ├── arch/                       ← 架构契约（25 篇；2026-10-08 批：回放引擎/
    │                                  数据管道/适配器/鉴权矩阵/脱敏纵深/env 契约/
    │                                  变更智能/迁移纪律——全带 file:line 引证）
    ├── reviews/                    ← 审查记录（三轮全库评审/主计划审计/SWOT/竞品差距）
    ├── references/                 ← v3 原始设想（43 节）+ 踩坑经验（46 条）
    └── superpowers/plans/          ← 每 Sprint 派生计划（含测试矩阵）
```

## 3. 怎么跑

```bash
# 后端（Python 3.12+，uv）
cd server && uv sync && uv run alembic upgrade head
cp .env.docker.example .env        # 填 LLM_*/NJMIND_*（gitignore 排除，永不提交）
uv run python -m app.create_user <用户名> <密码> admin   # 建号（S21 起需登录）
uv run uvicorn app.main:app --port 8710

# 三套测试（Windows：Node 命令前缀 export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"）
cd server && uv run pytest -q                    # 508 passed
cd server/web && npm test                        # 50 passed
cd extension && npm run build && npm test        # 31 passed

# 常驻可见浏览器（录制/回放全程用户可见）
cd server && uv run python ../scripts/live_browser.py 9222
#   配合 REPLAY_CDP_URL=http://127.0.0.1:9222 RECORD_CDP_URL=...
```

## 4. 关键机制速查

| 机制 | 位置 | 一句话 |
|---|---|---|
| C1 影子门控 | replay/plan.py `requires_confirmation` + runner | 写操作未确认 → 编译期定格 shadow run，零浏览器 |
| 语义定位 | replay/locate.py | 不用 CSS selector，5 级语义链，按钮改名不脆断 |
| 自愈闭环 | replay/repair.py + api/locate_proposals.py | 定位失败→LLM 提案→locate 实测验证→回放自愈→N 次晋升→supersede 生成 skill 新版本 |
| 视觉回归 | replay/visual.py | dHash 初筛+像素占比阈值，首次 PASS 建基线 |
| 性能漂移 | change/perf.py | 滚动中位数×1.5 判漂移，进四分类 drift |
| flaky 重跑 | runner `_attempt` | fail 自动重试一次，结果不一致标 flaky 进一致性统计 |
| 四分类 | change/classify.py + api/change.py | 纯函数可重算复现（G2 自验的架构级证明） |
| Playwright 导出 | replay/exporter.py | skill/flow → 自包含脚本，独立运行验证过 |
| LLM 边界 | llm/gateway.py + 各 verify 函数 | LLM 提案，确定性回查通过才生效 |

## 5. 当前进度与下一步（2026-10-02）

- **项目状态：开发进行时（非可交付产品）**。主计划 MVP→M1→M4 + v1.6-v2.0
  差距块功能已实现；核心管道端到端能跑；七系统核心业务链验证通过。
  距"可用产品"的差距清单与开发路线图：`docs/HANDOVER.md` §2-§3。
- **S43-4（2026-10-01/02）**：七系统核心业务链闭环——Snipe-IT 资产/禅道 QA/
  Odoo 销售/Dolibarr 订单/JeecgBoot 在线表单/ERPNext CRM/若依权限，23 技能
  学成、22 换参回放全 PASS、实体级验证（直查目标系统 DB/API）。
  详见 `demo/sprint43/user-test-report.md`。
- **平台化四阶段（2026-10-06）**：交互画像+指纹生成+URL 通配符配对+扩链
  52/52+Firefly 零代码接入——八系统 53 技能全绿。架构契约：
  `docs/arch/2026-10-07-platform-interaction-profile.md`；收口报告：
  `demo/sprint-v21-matrix/platform-phase-report.md`。
- **全库评审（2026-10-07）**：四域深审+6 处安全红线修复（网关 IP env 化/
  路径穿越/attribution 脱敏/执行器三重脱敏/CDP 网络证据脱敏/插件配对 401）：
  `docs/reviews/2026-10-07-full-codebase-audit.md`。
- **三轮全库评审（2026-10-08）**：七域深审"声称的语义是否真的成立"——🔴 9 项全修
  （viewer 角色收窄 WRITE_GUARD 31 端点/C1 确认取登录态/Skill.system 迁移漂移删列+drift 守卫/
  写水位 GET 噪声/脱敏词表四处漂移→一致性测试/注入模板转义/AdaptersView 错写系统/IP 兜底回归），
  🟡 43 修 34，缓修 34 项逐条附触发条件。报告：
  `docs/reviews/2026-10-08-full-codebase-audit-round3.md`。同期补 8 篇 arch 文档：
  replay-engine / ingestion-pipeline / adapters-subsystem / auth-and-role-matrix /
  redaction-defense-in-depth / env-contract / change-intelligence /
  schema-migration-discipline（全带 file:line 引证）。
- **测试基线**：server 722 / web 81 / extension 142（三套全绿是合并前提；
  conftest 每进程独立测试库——pytest 可并行）。
- **异常处理四层防线**（2026-10-10）：AK 四码分类+预算+熔断（机制层）/
  AM 期望-观测对比写水位+登录守卫（语义层）/假 pass 收口（判定层）/
  failureKind 三态呈现（呈现层）——设计见 specs/ AK+AM+AN 三篇。
- **近期工作**（2026-10-03 v2.1 方向变更）：~~JeecG 链式 override~~ ✅（S43-5 完成，
  row-anchor 换参注入+动态 id 断言归一，三链全 PASS 实体级验证）→ **块 AF 适配器
  架构**（基座+声明式系统清单：manifest schema/探针运行时/例程库/链编排器/向导 UI）
  + **块 AG 扩展执行后端**（chrome.debugger 插件桥接客户端回放，瘦执行器+双后端
  一致性）→ L5 迁移实测并行不阻塞。规格：主计划 §4 块 AF/AG + §7 v2.1 变更记录。
- **交接材料**：`docs/HANDOVER.md`（**继任开发任务书**——差距清单/路线图/
  环境运维/凭据模式/7 枚继任开发提示词）。
- 进度详情：`docs/specs/2026-09-24-master-delivery-plan.md`（§7 变更记录）与
  各 Sprint 的 `demo/sprintN/user-test-report.md`。

## 6. AI 学习提示词（接手时直接投喂）

> 完整套件（6 枚场景化：通用接手/E2E 排查/新系统接入/发版验证/代码审查/
> 汇报材料）见 `docs/HANDOVER.md` §8。以下为冷启动通用版：

```
你是 SkillLens 项目的全栈贡献者（需求/PM/开发/测试一体）。请按以下顺序学习并
遵守这个项目的全部纪律：

【第一步：读文档建立世界观】
1. docs/HANDOVER.md（交接总档——现状+环境+未竟项+提示词套件，最新）
2. AGENTS.md（操作宪法——阶段闸门仪式/TDD/安全红线/环境要点，必读必守）
3. PROJECT-GUIDE.md（项目导览——你正在读的这份的完整版）
4. docs/COLLABORATION-CHARTER.md（协作宪章——项目所有者的全部要求汇总）
5. docs/specs/2026-09-23-skilllens-mvp-design.md（产品宪法——C1/C2/C3 硬约束）
6. docs/specs/2026-09-24-master-delivery-plan.md（交付主计划 v2.0——唯一范围基准）
7. docs/references/project-lessons.md（踩坑经验库）

【第二步：理解代码骨架】
- server/README.md → extension/README.md → server/web/README.md
- 核心链路代码：app/replay/runner.py（回放编排+写判定）、app/replay/locate.py
  （语义定位）、app/ingestion/alignment.py（窗口对齐+动态值归一）、
  app/change/classify.py（四分类纯函数）、app/llm/gateway.py（LLM 统一出口）、
  extension/src/content/capture.ts（采集入口）

【铁律——违反任何一条都是事故】
1. C1 影子模式零例外：写操作未确认绝不执行；C3 全链路落库含失败调用。
2. LLM 只做命名/结构化/归因/提案，一切判定必须确定性可复现。
3. TDD 先红后绿；测试即规格（brief 与测试矛盾以测试为准）。
4. 任何新功能先查主计划，不在计划内则先修订主计划获确认再动手。
5. 每个 Sprint 必走闸门仪式：三套测试全绿→代码审查(耦合+安全)→文档补全→
   浏览器用户层实测(截图入库)→用户测试报告→合并 main+删分支。
6. 安全红线：真实 key/网关域名/凭据不入任何代码/测试/文档/提交/日志；
   llm_call_log 异常必须 URL 脱敏；提交前 diff 扫敏感串。
7. 成熟项目对照（强制）：修 bug 前先查目标系统官方 harness（Frappe cypress/
   Odoo tour/Healenium 评分），结论注明出处。
8. Debug 铁律：超时=有交互没识别到，先查页面现场（提示/弹窗/开态），不空等。
9. LLM 产物异常先查 llm_call_log 实际输入输出，别先怪模型。
10. 测试盲区要如实声明，不谎报"已验证"；能自验的全自己闭环。

【环境（Windows 开发机）】
- Node 命令前缀：export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"
  （系统 Node 22.10 会静默坏测试）；vite pin ~8.2.2。
- uv.lock 被本机镜像改写属正常，提交前 git checkout -- server/uv.lock。
- 浏览器自动化用 scripts/live_browser.py 常驻可见窗口（用户要求全程可见）。
- 目标系统容器端口/凭据注入模式/SW 冷启动等：docs/HANDOVER.md §4。

【当前状态】
M1-M4+v2.0+v2.1+平台化四阶段全部完成：八系统 53 技能全绿（矩阵 52/52）、
新系统零代码接入终验（Firefly III）、全库评审+安全红线 6 处修复完毕，测试
基线 506/54/83。待办：G4 真实试点团队指定（唯一外部输入）+ 评审记录不修
13 项（docs/reviews/2026-10-07-full-codebase-audit.md §三，私有化前置项
2 个）。你的第一个任务：跑通三套测试确认基线，然后读主计划
§7 变更记录了解演进史，再看 demo/sprint-v21-matrix/platform-phase-report.md
最近验收形态。
```
