# Sprint 18 夜间开发 Implementation Plan（块 G，M3 完整出口）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划块 G。G3 闸口（njmind 开发自动化授权）：用户已持续授权浏览器自动化操作 njmind（S11 建表单/加字段实测），本 Sprint 沿用该通道。

**Goal:** 需求 → 结构化开发计划 → （C1 门控确认）→ 浏览器自动实现 → 验证——夜间开发一例真跑通，M3 完整出口（开发+测试+评审全闭环）。

**Architecture:** ①**T1 dev_plan 模型+生成**：dev_plan 表（id/requirement_text/target_form String(100)/changes JSON（LLM 结构化的字段变更清单：[{op: add_field, field_type, label, key}]）/status draft|confirmed|executed|error/execution_log JSON/reviewed_by/created_at）。POST /api/v1/dev-plans {requirement_text, target_form}——LLM（purpose=dev_plan）把需求结构化成变更清单；**确定性回查**：target_form 必须存在（真库 evidence/skill 骨架含该 formCode 或直接探测 getFormConfigByCode——v1 用骨架签名匹配）、add_field 的 key 不得与已知字段冲突（v1 查 evidence_edge/骨架，宽松）。②**T2 C1 延伸门控**：POST /dev-plans/{id}/confirm（人工确认，同 expected-delta 模式）→ status=confirmed；POST /dev-plans/{id}/execute——**仅 confirmed 可执行**（409 否则）；执行走浏览器自动化。③**T3 自动实现执行器**：server/app/agents/dev_executor.py——Playwright（复用 REPLAY_CDP_URL 常驻窗口，全程可见）打开 target_form 设计器 → 按 changes 逐项加字段（复用 S11 实测模式：点字段类型/改名改 key/权限 JS 注入/保存）→ 抓 saveFormConfig 响应落 execution_log → status=executed；异常→error+log。④**T4 夜间一例**：真实需求"请假申请表单（qingjiashenqing）增加紧急联系电话字段"→ plan → confirm → execute → 验证（设计器重开确认字段存在）→ 四分类 observe 回归。

**Tech Stack:** 1 迁移（dev_plan 表）；LLM 1 次调用（结构化，宪法边界内）；浏览器自动化复用 S11 模式。

## Global Constraints

- **C1 延伸**：dev_plan 生成后只是 draft（计划不执行）；confirm 才可 execute——与 Expected Delta 同构的门控。
- C3：execution_log 全落库（每步动作+saveFormConfig 响应摘要）。
- LLM 边界：结构化需求为变更清单（命名/结构化）；回查/门控/执行全确定性。
- 测试基线：247/28/34；仪式全流程。

---

### Task 1: dev_plan 模型 + 生成端点（TDD + 迁移）
- 迁移：dev_plan 表。
- POST /api/v1/dev-plans：LLM 结构化 + 确定性回查（target_form 在 skill 骨架 URL 中出现过=已知表单；changes 的 op 白名单 add_field|rename_field；field_type 白名单=设计器字段类型）。
- GET /dev-plans（列表）/ GET /{id}。

### Task 2: confirm 门控（TDD）
- POST /dev-plans/{id}/confirm {reviewed_by} → confirmed（重复 confirm 409）。
- POST /dev-plans/{id}/execute → 非 confirmed 409（C1 延伸：draft 计划不可执行）。

### Task 3: 自动实现执行器（TDD 单元 + 真机）
- dev_executor.py：`async def execute_dev_plan(db, plan) -> DevPlan`——Playwright CDP 打开设计器（formCode=plan.target_form）→ 逐 change：加字段（点类型/填名/key/权限注入）→ 保存 → 抓响应。每步 append execution_log。单测：changes 解析与步骤编译纯函数；真机验证在 T4。
- execute 端点调用执行器。

### Task 4: 夜间一例 + 仪式收尾
- 真实需求："请假申请表单增加紧急联系电话字段（文本输入框）"→ 全链 → 验证字段真实存在 → observe 回归 njmind 保存流（确认无回归）。
- 全量三套 → 审查 → 文档 → 浏览器实测（dev-plans 工作台呈现——列表页或独立区块最小展示）→ 截图 → 合并。
