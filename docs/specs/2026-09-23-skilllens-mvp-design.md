# SkillLens — MVP 设计文档

> 日期：2026-09-23
> 状态：待评审（v2：补充 §0 愿景与阶段地图、§11 调研记录、§12 防跑偏清单）
> 原始设想：`docs/references/ai_software_learning_change_intelligence_v3.md`（v3）
> 一句话：通过 Chrome 插件观察真实用户如何使用软件，从 UI / Network / State 证据中归纳出 Skill 与 Outcome，形成 Evidence-backed System Model；版本更新时用 Expected Delta vs Observed Delta 做四分类变更智能报告。
> 防遗忘：本文件是项目的"宪法"——每个 Sprint 回顾对照 §0（方向）、§2（约束）、§12（清单）；外部证据与决策理由全部存档在 §11。

---

## 0. 终极愿景与阶段地图

### 0.1 终极愿景（北极星，永远不变）

> **白天人定义需求，晚上 AI 开发，后半夜 AI 测试，第二天早上人 Review PR。**

完整闭环（v3 文档第 31/43 节）：

```text
白天    人定义 Requirement + Acceptance Criteria → 系统生成 Expected Delta
晚上    Coding Agent：Requirement + Living System Model → Plan → Code → Build
后半夜  Browser Runner + API Test + Unit/Integration
        → New Observation → Observed Delta → Expected vs Observed
        → Regression → Drift Detection
第二天  输出变更报告（该变的/没变的/多变的/漂移的）+ PR → 人工 Review
```

支撑这个闭环的长期资产是 **Evidence-backed Living System Model**——它持续学习：

```
软件是什么 + 用户怎么使用 + 什么是正常 + 有哪些 Skill/Workflow
+ 哪些状态转换 + 哪些接口对应哪些行为
```

每次更新后回答三个问题：**应该变的有没有变？不应该变的有没有被破坏？变了以后结果对不对？**

### 0.2 商业定位（对外永远这样讲）

不卖"AI 自动生成测试"，不卖"AI Browser Agent"，卖：

> **让 AI 学会你们公司的软件，并在每次版本更新后自动判断：应该改变的有没有改变，不应该改变的有没有被破坏。**

国内落地形态：Chrome Extension + Local Agent + Docker 私有化部署；PII 脱敏、Secret 掩码、数据不出网、客户自带 LLM Key、可选本地模型。

### 0.3 阶段地图（入口/出口标准）

| Phase | 名称 | 目标 | 入口条件 | 出口标准（达成才算进入下一阶段） |
|-------|------|------|---------|------|
| **1（当前）** | Learn One Skill | 跑通"演示 → 归纳 → 回放 → 判定"最小闭环 | 本设计文档评审通过 | §9 的 8 条成功标准全部达成；njmind 上有 3~5 个 validated Skill |
| **2** | Real Traffic + Change Intelligence | 切换真实用户流量学习（硬性约束 C2）；补全 Outcome 层 4/5 证据；四分类报告在真实发版中持续可用 | Phase 1 出口达成 | 在团队测试常用系统上，真实流量归纳出的 Skill 置信度 ≥ 刻意演示基线的 80%；连续 2 次真实发版的四分类报告被团队认可有行动价值 |
| **3** | Night Engineering | 夜间 Coding Agent + Testing Agent（此时引入 LangGraph）；Impact Analysis：代码变更 → 选中受影响 Skill → 定向回归 | Phase 2 出口达成 | 一次真实需求在夜间自动开发+测试，第二天人工 Review 通过率可接受 |
| **4** | Full Loop | Requirement → Night Coding → Night Testing → Morning Review 完整闭环产品化 | Phase 3 出口达成 | 有 1 个付费客户/团队在私有化环境跑完整闭环 |

**阶段纪律**：任何 Phase 未达出口标准，不启动下一 Phase 的工作；每个 Sprint 回顾时对照 §12 防跑偏清单检查。

---

## 1. 背景与目标

### 1.1 产品定位

不卖"AI 自动生成测试"，也不卖"AI Browser Agent"，卖的是：

> 让 AI 学会你们公司的软件，并在每次版本更新后自动判断：应该改变的有没有改变，不应该改变的有没有被破坏。

差异化护城河（联网调研结论，2026-09）：

- 采集层（rrweb/OpenReplay）和执行层（Playwright/Stagehand）已成熟，**不自研**；
- Katalon TrueTest 已做"真实 Session → 自动测试"和"一句话需求直出脚本"，但**没有 Evidence Graph、没有 Expected/Observed Delta 四分类**；
- Spec-Driven Development 浪潮（OpenSpec 等）都假设有代码仓库，**黑盒无源码系统的 spec 验证无人占位**——这是 SkillLens 的位置。

### 1.2 MVP 目标（6 周，30h+/周）

跑通一条端到端链路：

```
演示 3~10 次 → 归纳 Skill + Outcome → 换参数 Replay → PASS/FAIL
                                                  ↓
改一个需求 → Expected Delta → 新版本 Observed Delta → 四分类报告
```

### 1.3 非目标（MVP 明确不做）

- 不学整个 ERP，只学 One Skill（目标 3~5 个 Skill 库）；
- 不做真实用户流量的噪声学习（Phase 2 硬性目标，见 §2 约束 C2）；
- 不做 Coding Agent / 夜间自动开发（Phase 3+）；
- 不做多用户、权限、SaaS 化（私有化单租户优先）；
- 不做移动端 / 非 Chromium 浏览器。

---

## 2. 已确认的关键决策

| # | 决策 | 内容 |
|---|------|------|
| D1 | 首个被学习系统 | 开发/调试用 njmind 低代码平台（UI 标准化、可重置、本人可同时扮演用户与开发者）；架构上适配层做成配置，后续切换到团队测试常用的真实系统只改配置不改核心 |
| D2 | MVP 切入点 | 双轨：主线跑通 Learn One Skill 全链路；演示轨每 2 周在 njmind 上做一次端到端演示 |
| D3 | 技术栈 | 插件 TypeScript（Manifest V3）；后端 Python（FastAPI）；Replay 用 Playwright；LLM 调用走自研薄封装 Gateway |
| D4 | LangGraph | Phase 1 **不用**。学习管道是确定性数据处理 + 少量 LLM 归纳调用，普通模块 + Pydantic 可测试性更好；Phase 3 夜间 Coding/Testing Agent 再引入 |
| D5 | 存储 | SQLite 起步（SQLAlchemy + Alembic 迁移），schema 按 PostgreSQL 兼容设计，私有化交付时无缝切换 |

### 硬性约束（用户明确要求）

- **C1 影子模式**：MVP 中有副作用的操作（审批、删除等）不执行 Replay，只观察真人操作并与预期对比。无副作用或环境可重置的操作才允许自动 Replay。
- **C2 Phase 2 强制真实流量**：Phase 2 起 Skill 归纳输入**必须**切换为真实用户流量，不允许继续依赖刻意演示。噪声处理（走错、中断、并行任务、废路径过滤）是 Phase 2 的核心工作，不是可选项。
- **C3 全链路持久化**：管道每一级的中间产物——原始事件、Transaction Window、Semantic Action、Skill 草稿、LLM 调用日志、Delta 报告——**全部落库**，不允许只存在内存或临时文件。任何一步可回放、可审计、可归因（支撑"先查实际输入再怪模型"的调试方式）。

---

## 3. 总体架构

```text
┌─────────────────────────────────────────────────────┐
│ ① Chrome Extension (TS, Manifest V3)                │
│    Sensor：UI/DOM/A11y + Action + Network 采集      │
└──────────────┬──────────────────────────────────────┘
               ▼  (批量上报, 本地缓冲, 断网重试)
┌─────────────────────────────────────────────────────┐
│ ② Ingestion Pipeline (Python, FastAPI)              │
│    脱敏 → 归一化 → Transaction Window → 关联 → Diff  │
└──────────────┬──────────────────────────────────────┘
               ▼
┌─────────────────────────────────────────────────────┐
│ ③ Learning Engine (Python)                          │
│    Task Segmentation → Skill Induction →            │
│    Outcome Model → Evidence Graph                   │
├─────────────────────────────────────────────────────┤
│ ④ LLM Gateway (Python，自研薄封装)                   │
│    统一调用 + call_logs 全量落库 + 可换模型          │
├─────────────────────────────────────────────────────┤
│ ⑤ Replay Runner (Playwright)                        │
│    语义定位回放 + 确定性断言 Verify                  │
├─────────────────────────────────────────────────────┤
│ ⑥ Change Intelligence Engine                        │
│    Expected Delta 生成 + Observed Delta 探测        │
│    + Expected/Missing/Unexpected/Drift 四分类       │
└─────────────────────────────────────────────────────┘
存储：SQLite（⑤⑥ 依赖 ③ 产出的 Skill 库与 Evidence Graph）
```

边界原则：①②⑤ 用成熟方案拼装，自研力量全部投在 ③⑥ 语义层。

---

## 4. 组件设计

### 4.1 Chrome Extension（①）

**职责**：Browser-side System Sensor。只采集，不判断。

采集内容：

- **UI 信息架构**：菜单层级、Breadcrumb、URL/Route、Page、Tab、Modal、Drawer、Form、Table、Toolbar、Button、Row Action（基于 DOM + ARIA role/label，不依赖框架）；
- **用户行为**：click / input / select / submit / upload / navigate（含事件目标元素的语义描述）；
- **Network**：method、URL、request body、response、status、requestId、timing、fetch/XHR、WebSocket 消息、Console、JS Error；
- **状态快照**：动作前 1s 与动作后网络空闲 2s 的可见状态（关键文本标签 + 表单值 + 表格行数等轻量信号，不做全 DOM 序列化）。

上报协议：本地 IndexedDB 缓冲 → 批量 POST 到本地 Agent（默认 `http://127.0.0.1:8710`）。敏感字段（Cookie、Authorization 头、密码框）在插件侧即脱敏，入库前二次脱敏（C3：脱敏前后均落库，脱敏规则本身也记录）。

**不做的**：不做录屏、不做全 DOM mirror（rrweb 式全量录制留作 Phase 2 真实流量场景的可选增强）。

### 4.2 Ingestion Pipeline（②）

处理顺序（每级产物落库，C3）：

```
raw_event（原始事件，仅追加）
  → redaction（脱敏标记）
  → normalized_event（URL 模板化 /orders/92382 → /orders/{id}）
  → transaction_window（以用户主动动作为锚点：前 1s 快照 + 后续网络空闲 2s 内的请求与状态变化）
  → semantic_action（一个窗口的语义化结果）
```

**Transaction Window 是全系统最关键的确定性环节**：锚点 = click/submit 类主动动作；窗口关闭条件 = 连续 2s 无新网络请求且 DOM 稳定。

**URL 模板化**：对路径中的数字、UUID、已知 ID 模式做参数化归纳，形成 `/orders/{id}`；同一模板下收集实际值作为变量候选。

### 4.3 Learning Engine（③）

输入：同一任务的 3~10 个刻意演示 Episode（MVP）；真实流量（Phase 2，约束 C2）。

**多 Episode 对齐**（核心技术点）：

1. 每个 Episode 已被切为 Semantic Action 序列；
2. 跨 Episode 做序列对齐（确定性 diff 为主）：不变部分 = 流程骨架，变化部分 = 变量（order_id、搜索词、数量等）；
3. LLM 只负责给变量和动作命名（`SubmitOrderForApproval`），并归纳 Skill YAML；
4. **确定性验证**：LLM 产出的 Skill 中引用的每个 API、每个状态转换，必须能在原始 Episode 证据中找到对应记录，找不到即降级为 `candidate` 状态。

**Skill 产物 schema**（对齐 v3 文档第 8 节）：

```yaml
skill:
  name: ApproveSalesOrder
  status: candidate | learned | validated   # 按 evidence_count 与跨 Episode 一致性晋升
  preconditions: { role: manager, order.status: pending_approval }
  inputs: { order_id: SalesOrder }
  strategies: [Todo → Detail → Approve, List → Search → Detail → Approve]
  expected_outcomes: [...]   # 引用 outcome_assertion 表
  observed_apis: [POST /orders/{id}/approve]
  confidence: 0.94
  version: 1                 # 语义层版本化，UI 实现层单独存
```

**Outcome Model（MVP 只做两层证据）**：

- 层 2 UI State Change（`待审批 → 已审批`）；两个来源：(a) **字段级 Before/After diff**——同一 API 模板在同一/相邻窗口的连续 reqBody 做确定性 diff，产出 `字段: A→B`（Sprint 3，纯 server 端）；(b) 插件侧锚点前后轻量状态快照（表单值/状态标签文本）→ Sprint 4 采集增强（与 Replay 的 Before/After 快照共用一套 schema）；
- 层 3 Runtime Outcome（`POST /approve → 200` + `GET /order/{id} → status=APPROVED`）。
- 层 4 历史不变量、层 5 多结果一致性 → Phase 2。

> 2026-09-24 用户补充裁定：字段级 Before/After 正式纳入范围（"存下来之前是什么、之后是什么"）——它是 Outcome 断言与 Change Intelligence 判断 Expected/Missing/Unexpected 的直接原料。

**Evidence Graph**：节点 = 实体/页面/动作/API/状态，边带 `evidence_count / confidence / sources / first_seen / last_seen`。MVP 用关系表表达（`evidence_edge`），不引入图数据库。

### 4.4 LLM Gateway（④）

自研薄封装，所有 LLM 调用必须经过它：

- 入参：`purpose`（归纳/命名/Expected Delta 生成/失败归因）、`prompt`、`model`；
- 产出：结果 + `llm_call_log` 完整记录（含原始 prompt、响应、token 用量、耗时、版本）；
- 模型可配置可替换（客户自带 Key / 本地模型，私有化要求）。

### 4.5 Replay Runner（⑤）

- 定位策略：Playwright `getByRole` + label 语义定位（`button "提交审批"`），**不录制 CSS selector**；
- 执行前检查副作用标记（C1）：`side_effect: none | resettable | destructive`，`destructive` 一律走影子模式；
- 换参数回放：变量从 Episode 对齐结果中注入新值；
- 断言：确定性优先——Outcome Model 的层 2/3 断言直接执行（UI 文本对比、API 响应字段对比），LLM 只在断言失败时做归因分析（截图 + 上下文 → 失败原因报告）。

### 4.6 Change Intelligence Engine（⑥）

- **Expected Delta**：需求文本 → LLM 结构化为 YAML schema（v3 第 21 节）→ **人工确认后生效**（MVP 必须有人审）；
- **Observed Delta**：新版本上重放 Skill 库 + 扫描 UI/API/状态差异；
- **四分类**：Expected / Missing / Unexpected / Drift，输出 `delta_report`；
- Drift 检测 MVP 只做时序对比（同操作前后耗时、响应结构 diff），统计学习留 Phase 2。

---

## 5. 数据模型（SQLite，Alembic 迁移）

```text
recording_session   一次采集会话（谁、哪个系统、哪个任务意图）
raw_event           原始事件流（append-only，含脱敏标记）
transaction_window  事务窗口（锚点动作 + 前后快照引用 + 窗口内事件引用）
semantic_action     语义动作（action_name, entity, ui_context, api_calls[],
                    state_before, state_after, variable_bindings）
episode             一次完整任务演示（semantic_action 序列引用）
skill               语义技能（name, status, version, yaml, confidence）
skill_strategy      Skill 的可选路径
outcome_assertion   断言（skill_id, layer[2|3], expression, evidence_count）
evidence_edge       证据图边（src, dst, type, evidence_count, confidence, first/last_seen）
replay_run          回放执行记录（skill_id, params, result, artifacts 路径）
expected_delta      版本化需求预期（requirement_id, version, yaml, reviewed_by）
observed_delta      观测差异（against: expected_delta_id）
delta_report        四分类结果（expected[], missing[], unexpected[], drift[]）
llm_call_log        每次 LLM 调用的完整输入输出（purpose, prompt, response, model, tokens, latency）
```

原则：所有表带 `created_at / updated_at`；`raw_event` 与 `llm_call_log` append-only；大对象（截图、完整响应体）存文件系统，表内存路径与哈希（仍是持久化，满足 C3）。

---

## 6. 仓库结构

```text
SkillLens/
├── extension/          # Chrome 插件 (TS, Vite + CRXJS)
├── server/             # FastAPI：ingestion + learning + change intelligence
│   ├── app/
│   │   ├── ingestion/  # ②
│   │   ├── learning/   # ③
│   │   ├── llm/        # ④ gateway
│   │   ├── replay/     # ⑤ runner 编排
│   │   ├── delta/      # ⑥
│   │   ├── models/     # SQLAlchemy models
│   │   └── api/
│   ├── tests/          # pytest（全量通过才算完成）
│   └── alembic/
├── runner/             # Playwright Replay Runner（独立进程，server 通过任务队列驱动）
├── docs/
│   ├── specs/          # 本文档及后续 spec
│   └── references/
└── demo/               # 演示轨：njmind 演示脚本与数据
```

---

## 7. Sprint 计划（1 周/Sprint，MVP 共 6 周 + Sprint 0）

| Sprint | 主线交付 | 演示轨节点 | 验收标准 |
|--------|---------|-----------|---------|
| 0 | 仓库骨架 + 插件 POC：在 njmind 上采到 UI/Action/Network 原始事件并落库 | — | raw_event 表里能看到一次完整表单操作的原始事件 |
| 1 | Ingestion：脱敏 + URL 模板化 + Transaction Window | 演示 1：一次"提交表单"被切成语义窗口 | semantic_action 正确关联 click ↔ POST ↔ 状态变化 |
| 2 | 多 Episode 对齐 + 变量识别 + LLM Gateway + Skill 归纳 | — | 3 次不同输入的演示归并为 1 个 Skill，变量正确识别 |
| 3 | LLM Gateway（llm_call_log 全量落库）+ Skill 归纳（LLM 命名 + 确定性回查防幻觉降级）+ 字段级 Before/After（reqBody 跨窗口 diff）+ Outcome 层 2/3 断言 | 演示 2：Skill 卡片展示（含证据计数与置信度） | 两次演示的 alignment 产出 1 个 learned 状态的 Skill（LLM 产物全部通过确定性回查）；字段变化能被 diff 出（字段: A→B） |
| 4 | Replay Runner：语义定位 + 换参数回放 + PASS/FAIL + 影子模式标记 | — | 换一组参数自动回放，正确判定 PASS；破坏一个断言能判 FAIL |
| 5 | Expected Delta 生成（人工确认）+ Observed Delta + 四分类报告 | 演示 3：njmind 改一个需求 → 输出报告 | 四分类中 Missing 和 Unexpected 至少各能被真实构造触发一次 |
| 6 | 端到端打磨 + 演示数据固化 + 私有化部署脚本（Docker Compose） | 压轴演示：完整闭环 | 从装插件到出报告 ≤ 30 分钟，全程可复现 |

**每个 Sprint 的完成定义**：主线验收标准达成 + server 端 pytest 全量通过 + 中间产物全部落库（C3）。

**Sprint 回顾时检查**：是否在 ③⑥ 之外投入了过多时间（是 → 砍掉，改用现成方案）。

---

## 8. 主要风险与对策

| 风险 | 对策 |
|------|------|
| Transaction Window 切分不准（异步请求晚到、轮询干扰） | 窗口参数可配置；Sprint 1 在 njmind 上用真实数据调参；保留原始事件可重切（C3 的直接收益） |
| 多 Episode 对齐在路径分叉时失败 | MVP 只要求同策略内对齐；不同策略（路径 A/B）先分桶再各自对齐 |
| LLM 归纳的 Skill 引用幻觉 | 确定性验证：所有 API/状态引用必须回查证据，否则降级 candidate |
| Replay 语义定位在 njmind 上不稳定 | njmind UI 标准化是优势；若 ARIA 不足，适配层配置补充 data-* 属性约定（只改配置） |
| 单人 6 周节奏失守 | 双轨中演示轨可牺牲；Sprint 5/6 可合并为"最小 Change Intelligence"（只做 Missing + Unexpected 两分类） |
| 竞品（Katalon 等）速度 | MVP 期间不追功能，把 Evidence Graph + 四分类做扎实，这是它们短期补不上的架构差异 |

---

## 9. 成功标准（MVP）

沿用 v3 文档第 39 节，7 条全部达成：

1. 同一 Skill 多次操作，系统能归并；
2. UI 路径不同，能识别为同一业务 Task；
3. 能恢复 Action ↔ Network ↔ State 三方关联；
4. 能自动识别变量，而不是死数据；
5. 能学习稳定 Outcome；
6. 能换一组参数 Replay；
7. 能正确判断 Replay 是否成功。

外加第 8 条：**能对一次真实需求变更输出四分类报告，且 Missing/Unexpected 可被人工构造验证**。

---

## 10. 后续阶段方向（详见 §0.3 阶段地图）

- Phase 2：真实用户流量学习（约束 C2）、历史不变量（层 4）、多结果一致性（层 5）、Drift 统计检测、rrweb 全量录制可选增强、切换到团队测试常用系统；
- Phase 3：夜间 Coding Agent + Testing Agent（此时引入 LangGraph）、Impact Analysis、Skill 版本演化管理；
- Phase 4：Requirement → Night Coding → Night Testing → Morning Review 完整闭环。

---

## 11. 调研记录（2026-09-23 联网调研）

> 本节是设计决策的外部证据存档，防止后续遗忘"为什么这么设计"。所有结论检索于 2026-09-23。

### 11.1 竞品与商业验证

| 对象 | 结论 | 对 SkillLens 的意义 | 来源 |
|------|------|---------------------|------|
| Katalon TrueTest | 已落地"真实用户 Session → Journey → 自动生成测试"；2026-05 更新支持"一句话描述需求，直出自动化脚本" | 方向被商业验证，但"需求直出脚本"已占掉 Phase 2 叙事的一半——差异化必须压在 Evidence Graph + 四分类上 | [Katalon 2026-05 更新](https://blog.csdn.net/oscar999/article/details/162077496)、[从需求直达执行](https://m.blog.csdn.net/oscar999/article/details/162015296)、[TrueTest 介绍](https://blog.csdn.net/oscar999/article/details/156063768) |
| UiPath "dark testing factory" | 2026-09 提出"夜间测试工厂/持续测试终于实现"的叙事 | "白天开发、夜里测试"已被大厂作为正式方向，巨头在快速进场，窗口在收窄 | [UiPath 博客](https://www.uipath.com/blog/ai/dark-testing-factory-continuous-testing-finally-realized) |
| UiPath Task Mining / SAP Signavio | Action → Step → Task 分层、多 Session → Variant → Process 是成熟商业方向 | "click 不是 Task"已被验证；语义分层是行业共识，不是我们独创的风险 | UiPath/Signavio 官方文档 |
| Meticulous / QA Wolf 等 | 基于真实流量/会话的回归测试赛道存在且活跃 | 采集→测试路线可行，但均无"需求预期 vs 实际"的四分类 | [QA Wolf 2026 AI 测试工具对比](https://www.qawolf.com/blog/the-12-best-ai-testing-tools-in-2026) |
| Raindrop | 2026-09 宣布 $50M Series A（AI 质量工具赛道） | 资本仍在热投此赛道，时机不晚 | [Yahoo Finance](https://finance.yahoo.com/technology/ai/articles/raindrop-announces-series-50m-total-190300152.html) |

### 11.2 学术/研究侧

| 对象 | 结论 | 对 SkillLens 的意义 | 来源 |
|------|------|---------------------|------|
| KnowAct-GUIClaw（arXiv 2026-07） | 个人 GUI Agent 从交互中构建知识、沉淀可复用 Skill | Semantic Action/Skill 思路与研究前沿同源 | [arXiv 2607.12625](https://arxiv.org/html/2607.12625v2) |
| Agent Skills for LLMs（arXiv 2026-02） | Skill 的架构、获取、演化已成独立研究议题 | Skill 版本化设计（§4.3）可直接借鉴其框架 | [arXiv 2602.12430](https://arxiv.org/html/2602.12430v4) |
| LearnAct / GOAL（GUI-Observe-API-Learn） | "看用户演示 → 提取可复用经验 → 指导新 GUI 任务"是 GUI Agent 明确研究方向；"GUI 是语义入口，API 是事实证据"与本项目路线一致 | v3 文档第 17 节引用的方向在 2026 年被持续验证 | arXiv / v3 文档 §17 |
| Spec-Driven Development 浪潮 | OpenSpec、arXiv 论文等把"需求结构化为可验证契约"当成 AI 编码时代核心问题；**但全部假设有代码仓库** | SkillLens 的 Expected Delta 是给"黑盒无源码系统"做 spec 验证——SDD 浪潮里目前无人占位，这是顺风也是空位 | [OpenSpec](https://recca0120.github.io/en/2026/03/08/openspec-sdd/)、[arXiv 2602.00180](https://arxiv.org/pdf/2602.00180)、[火山引擎需求工程 Skill](https://developer.volcengine.com/articles/7628812877517848603) |
| "LLM 评审不能替代确定性校验" | 确定性校验与 LLM 评审存在"通道鸿沟"，LLM Judge 有系统性盲区 | 独立印证 v3 §11 的证据优先级设计；可直接用于对外话术 | [文章链接](https://feinterview.poetries.top/ai-monitor/news/the-channel-gap-why-your-llm-judge-is-blind-in-one-eye) |

### 11.3 国内需求信号

| 信号 | 结论 | 来源 |
|------|------|------|
| 企业 AI 智能体选型关注"伪私有化合规陷阱" | 私有化是真需求，且客户开始有能力辨别"伪私有化"——数据不出网必须是架构级承诺而非话术 | [百家号](https://baijiahao.baidu.com/s?id=1874048988065332208) |
| 企业内网部署大模型落地与避坑 | 内网/离线运行能力是选型硬指标 | [避坑指南](http://www.mhpq.cn/news/407373) |
| 信创 RPA 内网部署与离线运行横评 | 信创环境兼容性是进入国企/政府类客户的门槛 | [选型指南](https://baijiahao.baidu.com/s/for=pc&id=1875008514286360408&wfr=spider) |
| 国内已有 AI 测试平台（爱测等） | 国内玩家都是"测试平台"叙事，无人做"Change Intelligence/需求验证"叙事——§0.2 的卖点定位成立 | [凤凰网财经](https://finance.ifeng.com/c/8wWZ09SxKbM) |

### 11.4 调研结论对设计的四条直接影响

1. **不自研采集层和执行层**（rrweb/OpenReplay、Playwright/Stagehand 已成熟，无差异化价值）→ §3 边界原则；
2. **差异化压在 Evidence Graph + Expected/Observed Delta 四分类**（Katalon 已占"需求直出脚本"，不能正面撞）→ §0.2、§8；
3. **黑盒无源码系统的 spec 验证是 SDD 浪潮中的空位**（所有 SDD 工具都假设有代码仓库）→ 长期叙事；
4. **私有化/数据不出网做成架构级默认**（国内客户已会辨别伪私有化）→ §0.2、Sprint 6 交付 Docker Compose。

---

## 12. 防跑偏检查清单（每个 Sprint 回顾必查）

> 项目最常见的死法不是技术失败，是做着做着忘了为什么出发。以下问题在每个 Sprint 回顾时逐条自问，任何一条答"否"都必须在下一个 Sprint 修正。

**方向类：**

1. 本 Sprint 做的事，是否让"演示 → 归纳 → 回放 → 判定 → 四分类报告"这条主链路离可用更近了？（纯基础设施优化不算，除非它阻塞主链路）
2. 是否在 ③ Learning Engine / ⑥ Change Intelligence 之外的组件上投入了超过 30% 的时间？（是 → 砍掉，换现成方案）
3. 卖点叙事是否仍然是 §0.2 的那句话？有没有不知不觉滑向"又一个测试工具"或"又一个浏览器 Agent"？
4. 是否遵守了阶段纪律（§0.3）：没有提前做 Phase 2/3 的事（尤其是：没有提前碰真实流量噪声、没有提前碰 Coding Agent）？

**约束类：**

5. C1：本 Sprint 有没有任何一次对 destructive 操作的自动 Replay？（必须为 0）
6. C2：Phase 1 的所有 Skill 归纳输入是否都来自刻意演示且已明确标记？（Phase 2 切换真实流量时才有基线可比）
7. C3：本 Sprint 新增的管道环节，中间产物是否全部落库？抽查一条数据能否从 delta_report 一路回溯到 raw_event？
8. LLM 产物是否全部经过确定性回查验证（引用的 API/状态能在证据中找到）？

**节奏类：**

9. 本 Sprint 验收标准是否客观达成（而非"大概行了"）？server 端 pytest 是否全量通过？
10. 演示轨节点是否如期产出？如果连续 2 个 Sprint 没有可演示的东西，说明主线在空转，立即停下来重新对齐。

---
