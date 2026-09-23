# AI Software Learning & Change Intelligence Engine
## —— 从“浏览器学习系统”到“夜间开发 + 增量验证”的完整思路整理

> 版本：v3  
> 日期：2026-09-22  
> 目的：整理当前关于“如何利用大量 LLM Token、24 小时服务器、开发经验与 Harness 能力，做一个可以在国内落地并形成副业收入的 AI 工程产品”的完整思路。  
>
> 本版重点收敛：
>
> - 第一版不走纯 API 测试；
> - Chrome 插件作为核心学习入口；
> - AI 通过真实用户行为学习软件“怎么使用”；
> - UI、Network、State、API、页面结构共同形成语义；
> - 无源码条件下构建 Evidence-backed System Model；
> - 从演示与历史行为归纳 Skill / Task / Workflow；
> - 通过历史成功样本与状态变化学习“什么算做对”；
> - 新需求通过 Expected Delta 描述“应该发生什么变化”；
> - 新版本通过 Change Intelligence 判断 Expected / Missing / Unexpected / Drift；
> - 最终目标是支持“白天定义需求，晚上 AI 开发，后半夜 AI 测试，第二天 Review PR”。

---

# 1. 起因

现有资源条件：

- 有多个可用的 LLM Token 订阅；
- Token 能力主要用于文本、多模态理解和文本生成；
- 有可 24 小时运行的服务器与测试机；
- 有丰富的软件开发经验；
- 有较强的 Harness / 自动化 / 工程编排能力；
- 希望做一个：
  - 一个人可以先做 MVP；
  - 自动化程度高；
  - 能够利用夜间算力和 Token；
  - 不依赖特定行业经验；
  - 可以在国内私有部署或企业内部使用；
  - 最终可以副业变现的技术产品。

最初问题：

> **怎么把 Token + 24h Server + 软件开发 + Harness 能力组合起来，形成真正有商业价值的副业？**

---

# 2. 早期方向：Agent / LLM 自动化测试

最开始考虑：

```text
Dataset
  ↓
Agent / API
  ↓
Trace
  ↓
Evaluator
  ↓
Regression Report
```

关注：

- Tool Calling；
- 幻觉；
- Token；
- Latency；
- Prompt Regression；
- Model Regression；
- Output correctness。

但很快发现：

> 市场上 LangSmith、Braintrust、Langfuse、Weave、DeepEval、Promptfoo 等已经做得很成熟。

因此，单纯做：

> “Agent Eval Platform”

缺乏足够差异。

---

# 3. 从 API 测试走向真实软件使用

继续讨论后出现了一个关键问题：

> 用户真正使用软件，不是在调用 API，而是在浏览器里操作菜单、页面、Tab、表格、弹窗、表单和按钮。

例如一个 ERP 流程：

```text
销售管理
→ 销售订单
→ 待审批 Tab
→ 搜索订单
→ 打开详情
→ 审批记录
→ 审批通过
```

纯 API 只能看到：

```text
POST /api/order/{id}/approve
```

但它不知道：

- 用户为什么来到这个页面；
- 当前是什么角色；
- 哪个 Tab 很重要；
- 操作前应该检查什么；
- 用户通常通过什么路径进入；
- UI 最终应该变成什么；
- 哪些行为属于“正确流程”。

因此：

> **API 是证据，但不能作为产品的全部。**

---

# 4. Chrome 插件成为核心入口

最终更倾向于：

> **Chrome Extension 不是辅助工具，而是系统学习入口。**

它的角色不是 Recorder，而是：

# Browser-side System Sensor

它持续观察真实用户如何使用软件。

---

# 5. 插件应该采集什么

## 5.1 UI 信息架构

需要采：

- 一级菜单；
- 二级菜单；
- Breadcrumb；
- URL / Route；
- Page；
- Tab；
- Modal；
- Drawer；
- Wizard；
- Form；
- Table；
- Toolbar；
- Filter；
- Button；
- Row Action；
- Bulk Action；
- 页面可见状态。

例如：

```text
销售管理
├── 销售订单
│   ├── 订单列表
│   │   ├── 全部
│   │   ├── 草稿
│   │   └── 待审批
│   └── 订单详情
│       ├── 基本信息
│       ├── 商品明细
│       ├── 审批记录
│       └── 物流信息
```

这些信息构成：

> **UI Graph**

---

## 5.2 用户行为

例如：

```text
click
input
select
submit
upload
navigate
row action
bulk action
```

但不能把这些低层 Event 直接当 Workflow。

---

## 5.3 Runtime / Network

插件可以观察：

- HTTP method；
- URL；
- request body；
- response；
- status code；
- requestId；
- initiator；
- timing；
- fetch/XHR；
- WebSocket；
- Console；
- JS Error；
- 页面状态变化。

例如：

```text
点击：
提交审批

随后：
POST /api/order/123/submit

然后：
GET /api/order/123

最终：
DRAFT → PENDING_APPROVAL
```

---

# 6. 不能保存“点击脚本”，要形成 Semantic Action

低层 Event：

```text
click button
```

没有长期价值。

应该抽象成：

```yaml
action:
  name: SubmitOrderForApproval

entity:
  type: SalesOrder

ui:
  page: SalesOrder.Detail
  button: 提交审批

runtime:
  endpoint:
    method: POST
    path: /orders/{id}/submit

state_transition:
  from: DRAFT
  to: PENDING_APPROVAL
```

这就是：

# Semantic Action

未来 UI 即使变化：

```text
提交审批
```

变成：

```text
提交审核
```

只要业务语义没变：

```text
SubmitOrderForApproval
```

这个 Skill 就仍然存在。

---

# 7. 为什么要学习 Skill，而不是学习脚本

例如两个人审批订单：

### 路径 A

```text
销售订单
→ 搜索订单
→ 详情
→ 审批
```

### 路径 B

```text
待办中心
→ 打开订单
→ 审批
```

低层 Recorder 会认为：

> 两条完全不同的脚本。

但真正的 System Learning 应该抽象成：

```text
Skill:
ApproveSalesOrder(order_id)
```

下面允许多个 Strategy：

```text
Strategy A:
Order List → Search → Detail → Approve

Strategy B:
Todo → Order → Approve
```

因此 AI 学会的是：

> **“审批订单”这个 Skill**

而不是：

> “点哪几个按钮”。

---

# 8. Skill 应该包含什么

例如：

```yaml
skill:
  name: ApproveSalesOrder

preconditions:
  role: manager
  order.status: pending_approval

inputs:
  order_id:
    type: SalesOrder

possible_entry_points:
  - Todo
  - SalesOrder.List

strategies:
  - Todo → Detail → Approve
  - SalesOrder.List → Search → Detail → Approve

expected_outcomes:
  - order.status == approved
  - approval_record_added == true

observed_apis:
  - POST /orders/{id}/approve
  - GET /orders/{id}

confidence:
  0.96
```

---

# 9. 学“怎么做”和学“什么算对”是两个问题

这是整个系统非常重要的架构分离。

## Skill / Policy Learning

回答：

> 怎么完成任务？

例如：

```text
ApproveSalesOrder
```

---

## Oracle / Outcome Learning

回答：

> 什么算完成正确？

例如：

```text
订单状态变成 APPROVED
审批记录新增
订单仍可查询
```

不能把二者混为一谈。

---

# 10. “对错”应该从哪些证据学习

推荐从五层证据建立 Outcome Model。

## 第一层：显式成功提示

例如：

```text
审批成功
```

这种证据有价值，但比较弱。

## 第二层：UI State Change

例如：

```text
Before:
待审批

After:
已审批
```

长期重复出现，可以形成：

```text
ApproveSalesOrder
⇒
status == APPROVED
```

## 第三层：Runtime Outcome

例如：

```text
POST /approve
→ 200

GET /order/{id}
→ status = APPROVED
```

UI 和 API 同时证明成功。

## 第四层：历史成功样本

例如过去 500 次：

```text
Pending
→ Approve
→ Approved
```

出现 499 次。

如果某次：

```text
Pending
→ Approve
→ Pending
```

就属于异常。

这就是：

> **Historical Invariant**

## 第五层：多结果一致性

创建订单以后，不仅检查：

```text
Toast = 创建成功
```

还检查：

```text
订单列表出现
+
详情数据正确
+
status = DRAFT
+
API 能查到
```

这叫：

# Outcome Model

---

# 11. “对错”不能主要依赖 LLM Judge

推荐优先级：

```text
Deterministic Evidence
↓
Historical Invariant
↓
Cross-source Consistency
↓
LLM Semantic Judge
```

LLM Judge 主要处理：

- 自然语言；
- 非结构化结果；
- 含义判断；
- 模糊业务规则。

结构化状态尽量不用 LLM 判断。

---

# 12. 无源码条件下，能做到什么？

必须接受一个边界：

> **没有源码时，不能恢复真实后端实现，只能恢复“被观察到的行为模型”。**

例如真实后端可能：

```text
Browser
→ API Gateway
→ OrderService
→ ApprovalService
→ Kafka
→ InventoryService
```

插件只看到：

```text
Browser
→ POST /orders/{id}/approve
→ Response
```

因此不能编造内部链路。

---

# 13. 因此系统应该是 Evidence-backed，而不是 AI 总结

知识应该分层：

```text
L0 Observation
↓
L1 Normalized Fact
↓
L2 Correlation
↓
L3 Semantic Hypothesis
↓
L4 Validated Knowledge
```

例如：

### L0

```text
POST /order/92382/submit
POST /order/92881/submit
```

### L1

```text
POST /order/{id}/submit
```

### L2

```text
Click("提交审批")
↔
POST /order/{id}/submit
```

### L3

```text
SubmitOrderForApproval
```

### L4

通过几十/几百次观察验证后：

```text
Validated Skill:
SubmitOrderForApproval
```

---

# 14. Evidence Graph

最终知识不能只是一份 Markdown 总结。

应该形成图结构：

```text
SalesOrder
   │
   ▼
Order Detail
   │
   ▼
Submit Approval
  /            ▼             ▼
POST /submit   PENDING_APPROVAL
   │
   ▼
GET /order/{id}
```

每条边带：

```yaml
evidence_count: 237
confidence: 0.97
sources:
  - ui
  - network
  - runtime
validated: true
first_seen: ...
last_seen: ...
```

这个结构是后续所有 Agent 的基础。

---

# 15. Transaction Window

一次用户动作不应该只看 click。

需要构建：

```text
Before Snapshot
      ↓
Action
      ↓
Network / DOM / State Observation
      ↓
After Snapshot
```

最终 Semantic Action 来自：

```text
Before
+
Action
+
Network
+
After
```

---

# 16. Passive Learning + Active Probing

纯被动观察不够。

## Passive Learning

从真实用户中学习：

- 高频路径；
- 常用功能；
- 真实分支；
- 实际入口；
- 用户习惯。

## Active Probing

在测试环境主动验证规则。

例如观察到：

```text
5000 → 普通审批
8000 → 普通审批
20000 → 经理审批
50000 → 经理审批
```

系统猜测：

```text
amount > threshold
→ manager approval
```

再主动测试：

```text
9999
10000
10001
```

最后形成：

```yaml
rule:
  if:
    amount: "> 10000"

  then:
    approval_level: manager
```

---

# 17. 商业与论文参照

## Katalon TrueTest

核心：

```text
真实用户 Session
→ Journey Map
→ 高频 Flow
→ 自动生成测试
```

说明：

> “真实使用行为 → 测试”已经被商业验证。

## UiPath Task Mining

核心：

```text
Action
↓
Step
↓
Task
```

重要启发：

> click 不是 Task。

## Microsoft / SAP Signavio

说明：

> 多 Session → Variant → Process 是成熟商业方向。

## OpenReplay / rrweb

说明：

> DOM + Event + Network + Replay 采集基础能力已经成熟。

## SmartRPA

说明：

```text
UI Log
↓
Routine
↓
Variation Point
↓
Automation
```

历史行为可以部分自动归纳出可执行流程。

## task-recognition

说明：

```text
UI Event
↓
Segmentation
↓
Task Recognition
↓
Object Correlation
```

是从低层 Event 到业务 Task 的关键研究路径。

## Stagehand / Browser Agent

启发：

```text
Known
→ deterministic

Unknown
→ AI fallback
```

不应该每一步都调用 LLM。

## GOAL：GUI-Observe-API-Learn

核心思想：

```text
GUI Workflow
↓
API Observation
↓
Intent Understanding
↓
Reusable Skill
```

与本项目“GUI 是语义入口，API 是事实证据”的路线高度一致。

## LearnAct

核心思想：

```text
看用户 Demonstration
↓
提取可复用经验
↓
指导新的 GUI Task
```

说明：

> “AI 通过看人操作学习软件”是当前 GUI Agent 很明确的研究方向。

## Screenshot-based Task Mining

说明：

> 页面状态和截图可以帮助恢复用户为什么走某个业务分支。

---

# 18. 第一版不应该是纯 API 产品

虽然 Traffic → Test 很容易落地，但如果第一版只做 API：

优势：

- 简单；
- 快；
- 易卖。

但缺点：

- 容易退化成接口测试工具；
- 难以学习用户真实操作；
- 难以理解页面语义；
- 难以形成长期 System Context；
- 产品天花板较低。

因此更合理的是：

> **插件一定保留。**

API / Network 是插件下面的：

# Fact Layer

而不是全部。

---

# 19. 第一版应该学什么？

不要一开始学整个 ERP。

第一版只学：

# One Task / One Skill

例如：

```text
创建订单
```

让用户正常做几次。

系统自动输出：

```text
Skill Name
Precondition
Input Variables
Entry Points
Important UI
Action Sequence
Related APIs
Expected Outcome
Alternative Paths
Confidence
```

然后能够：

```text
换一组输入
↓
自动 Replay
↓
自动判断 PASS / FAIL
```

这已经足够强。

---

# 20. 系统增量更新：另一个核心问题

系统不是静态的。

每天会：

- 新增需求；
- 修改旧功能；
- 改 UI；
- 改接口；
- 改状态；
- 增加新流程。

因此不能：

> 每次更新后重新学习整个系统。

必须引入：

# Delta Learning / Change Intelligence

---

# 21. 新需求应该先变成 Expected Delta

例如需求：

> 销售订单增加“复制订单”。

应该自动结构化成：

```yaml
feature: CopySalesOrder

expected_changes:

  ui:
    page: SalesOrder.Detail

    add_action:
      name: copy_order
      label: 复制订单

  behavior:
    create_new_order: true

  copy_fields:
    - customer
    - items
    - quantity

  reset_fields:
    - order_id
    - status
    - approval_history

  expected_state:
    new_order.status: DRAFT
```

这叫：

# Expected Delta

它回答：

> **这次系统“应该”怎么变化。**

---

# 22. 新版本实际发生的变化叫 Observed Delta

更新后插件发现：

```text
新增按钮：
复制订单

新增接口：
POST /orders/{id}/copy

新订单状态：
DRAFT
```

形成：

```yaml
observed_changes:

  ui:
    added_action:
      Copy

  api:
    added:
      POST /orders/{id}/copy

  state:
    new_transition:
      action: Copy
      target: DRAFT
```

---

# 23. Expected Delta vs Observed Delta

这是新版本验证的核心。

例如：

```text
需求预期                     实际
---------------------------------------
新增 Copy Button             ✓
新增 Copy API                ✓
复制 customer                ✓
复制 items                   ✓
新订单 status = DRAFT        ✓
不复制 approval_history      ✗
```

得到：

```text
5 / 6 PASS

FAIL:
approval_history unexpectedly copied
```

这已经接近真正意义上的：

# Requirement Validation

---

# 24. Change Intelligence 的四种变化

每次更新后，系统应该把变化分成四类：

## 1. Expected Change

需求说要变，实际也正确变化。

## 2. Missing Change

需求说要变，但实际没有。

## 3. Unexpected Change

需求没说要变，但实际变了。

通常是 Regression 高风险区。

## 4. Behavior Drift

UI/API 表面没变，但行为变了。

例如：

```text
过去：
Submit → 500ms → Approved

现在：
Submit → 8s → Approved
```

---

# 25. Change Intelligence Engine

完整模型：

```text
                     Requirement
                         │
                         ▼
                  Expected Delta

                         │
                         ▼

Old System Model ──→ Change Engine ←── New Observation
                         │
                         ▼

          ┌──────────────┼──────────────┐
          ▼              ▼              ▼

      Expected         Missing       Unexpected

                         │
                         ▼

                        Drift
```

---

# 26. 为什么新功能不能只靠历史学习

老功能：

```text
Historical Behavior
→ 可以帮助形成 Oracle
```

新功能：

```text
历史上根本不存在
```

所以新功能的 Oracle 必须主要来自：

```text
Requirement
+
Acceptance Criteria
```

因此：

```text
旧功能：
History → Oracle

新功能：
Requirement → Oracle
```

---

# 27. 新功能第一次出现时怎么学？

如果 System Context 里以前没有：

```text
SplitSalesOrder
```

更新后插件发现：

```text
新增：
拆分订单
```

第一次有人使用：

```text
订单详情
→ 拆分订单
→ 选择商品
→ 填数量
→ 确认
```

系统创建：

```yaml
candidate_skill:

  name:
    SplitSalesOrder ?

  observed_count:
    1

  confidence:
    0.45
```

随着更多使用：

```text
Candidate
↓
Learned
↓
Validated
```

---

# 28. Requirement 可以作为 Prior Knowledge

如果需求已经告诉系统：

```text
新增：
SplitSalesOrder
```

那么插件看到：

```text
拆分订单按钮
```

时就不需要重新猜。

可以直接做：

```text
Requirement
↔
Observed Feature
```

因此：

> **Requirement 是新版本学习的重要先验。**

---

# 29. Skill 和 Workflow 都必须版本化

例如：

```text
Workflow V1

Create
→ Submit
→ Approve
```

新需求加入：

```text
FinanceConfirm
```

变成：

```text
Workflow V2

Create
→ Submit
→ Approve
→ FinanceConfirm
```

不能覆盖旧版本。

需要知道：

- 从什么时候生效；
- 哪个版本属于哪个发布；
- 哪些测试对应哪个版本。

---

# 30. Semantic Skill 与 UI Implementation 必须分层

例如业务 Skill：

```text
ApproveSalesOrder
```

UI V1：

```text
按钮：
审批通过
```

UI V2：

```text
按钮：
确认审批
```

Semantic Skill 没有变化。

因此必须分：

```text
Semantic Layer

ApproveSalesOrder
```

和：

```text
Implementation Layer

V1:
button = 审批通过

V2:
button = 确认审批
```

这样 UI 变化不等于业务 Skill 重学。

---

# 31. Browser Sensor + Change Intelligence + Night Engineering

这三个部分最终可以形成完整闭环。

## 白天

人定义：

```text
Requirement
+
Acceptance Criteria
```

系统生成：

```text
Expected Delta
```

## 晚上

Coding Agent：

```text
Requirement
+
Living System Model
↓
Plan
↓
Code
↓
Build
```

## 后半夜

```text
Browser Runner
+
API Test
+
Unit / Integration
↓
New Observation
↓
Observed Delta
↓
Expected vs Observed
↓
Regression
↓
Drift Detection
```

## 第二天

输出：

```text
Feature #183

Expected changes:
6

Correct:
5

Incorrect:
1

Unexpected changes:
2

Behavior drift:
1

Risk:
Approval Flow affected

PR:
#421
```

---

# 32. 最终产品并不是“自动化测试平台”

它更像：

# AI Software Learning & Change Intelligence Engine

长期学习：

```text
软件是什么
+
用户怎么使用
+
什么是正常
+
有哪些 Skill
+
哪些 Workflow
+
哪些状态转换
+
哪些接口对应哪些行为
```

每次更新以后，再判断：

```text
应该变的有没有变？
不应该变的有没有乱变？
变了以后结果是不是正确？
```

---

# 33. 整体系统架构

```text
                    Human User
                        │
                        ▼
                Chrome Extension
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
          UI          Action       Network
           │            │            │
           └────────────┼────────────┘
                        ▼
                   State Diff
                        │
                        ▼
                Semantic Episode
                        │
                        ▼
                 Skill Learning
                        │
                        ▼
               Outcome / Oracle
                        │
                        ▼
          Evidence-backed System Model
                        │
            ┌───────────┼───────────┐
            ▼           ▼           ▼
         Coding       Testing     Review
          Agent        Agent       Agent
```

增量更新时：

```text
Requirement
   ↓
Expected Delta
   ↓

Old Model
   ↓
Change Intelligence
   ↑
New Observation

   ↓

Expected
Missing
Unexpected
Drift
```

---

# 34. 第一版 MVP 应该怎么做

第一版不要：

- 理解整个 ERP；
- 自动开发；
- 自动分析所有业务；
- 做完整 Process Mining；
- 做完整测试平台。

只做：

# Learn One Skill

---

# 35. MVP 输入

用户在 Chrome 中正常做一个任务 3～10 次。

例如：

```text
审批订单
```

---

# 36. MVP 插件采集

```text
Page
Tab
Button
Form
Table
DOM / Accessibility
Action
Network
Request Params
Response
Before State
After State
Screenshot（必要时）
```

---

# 37. MVP Pipeline

```text
Raw Events
↓
Noise Filtering
↓
PII / Secret Redaction
↓
Transaction Window
↓
UI / Network Correlation
↓
State Diff
↓
Semantic Action
↓
Episode
↓
Task Segmentation
↓
Skill Induction
↓
Outcome Model
↓
Replay
↓
Verify
```

---

# 38. MVP 输出

例如：

```text
Skill:
ApproveSalesOrder

Input:
order_id

Preconditions:
role = manager
status = pending

Strategy A:
Todo → Detail → Approve

Strategy B:
Order List → Search → Detail → Approve

Expected Outcome:
status = approved

Observed APIs:
POST /orders/{id}/approve

Confidence:
94%
```

然后：

```text
Replay with new order
```

自动判断：

```text
PASS / FAIL
```

---

# 39. MVP 成功标准

1. 同一个 Skill 多次操作，系统能归并。
2. UI 路径不同，但能识别为同一个业务 Task。
3. 能够恢复 Action ↔ Network ↔ State。
4. 能够自动识别变量，而不是死数据。
5. 能够学习稳定 Outcome。
6. 能够换一组参数 Replay。
7. 能够正确判断 Replay 是否成功。

---

# 40. 后续演进

## Phase 1

```text
Observe
→ Learn
→ Replay
→ Verify
```

## Phase 2

```text
Requirement
→ Expected Delta
→ New Version
→ Change Intelligence
```

## Phase 3

```text
Code Change
→ Impact Analysis
→ Select Learned Skills
→ Regression
```

## Phase 4

```text
Requirement
→ Night Coding
→ Night Testing
→ Morning Review
```

---

# 41. 国内落地策略

国内企业真正会关心：

- 业务数据；
- Cookie；
- Token；
- 请求参数；
- 内网系统；
- ERP / CRM；
- 数据安全；
- 私有化。

因此产品应该天然支持：

```text
Chrome Extension
+
Local Agent
+
Docker Private Deployment
```

并支持：

```text
PII Redaction
Secret Masking
Local Processing
Data Never Leaves Network
Customer-owned LLM Key
Optional Local Model
```

---

# 42. 最终商业卖点

不要卖：

> “AI 自动生成测试。”

也不要卖：

> “AI Browser Agent。”

而应该卖：

> **让 AI 学会你们公司的软件，并在每次版本更新后自动判断：应该改变的有没有改变，不应该改变的有没有被破坏。**

---

# 43. 一句话总结

> **通过 Chrome 插件观察真实用户如何使用软件，结合 UI、Network、State 和历史结果，逐渐学习系统的 Skill、Workflow 与正确结果，形成 Evidence-backed Living System Model；当需求增量更新时，用 Expected Delta 与新版本 Observed Delta 做 Change Intelligence，从而支撑夜间自动开发、自动回归和第二天人工 Review。**
