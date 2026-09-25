# Sprint 15 晨间评审 + Skill 演化 Implementation Plan（块 I，M3 收尾）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划块 I。前置：S13/S14（agent_run/画布/批回放就绪）。

**Goal:** 晨间评审门户（夜间产物的 PR 式评审流）+ Skill 版本演化管理（v3 §29：不覆盖旧版本）+ 夜间全流水线一例（M3 出口验证——G 块夜间开发卡 G3，以"定向回归流水线+评审"作为 M3 可达成部分的出口验证）。

**Architecture:** ①**I1 评审门户**：`review` 表（id/agent_run_id FK/reviewer/decision approved|rejected|changes_requested/comment/created_at）+ 端点（POST /reviews 创建评审、GET /reviews?status= 列表、GET /reviews/{id}）+ 前端 `/reviews-portal` 路由——评审队列（未评审 agent_run 列表，含画布摘要/review 节点 markdown）→ 评审表单（通过/驳回/打回 + 评语）→ 已评审列表。**注意与四分类报告页（/reports/:deltaId）区分**：本页评审的是**夜间运行**（agent_run），报告页看的是发版四分类。②**I2 Skill 版本演化**：skill 表加 `version`（default 1）与 `superseded_by`（nullable FK）——re-induce 不再删除旧 skill，改为：旧行 status→"superseded"+superseded_by=新行 id，新行 version=旧 max+1；断言/策略跟随新行（旧行断言保留作历史，verify 端点对 superseded 行返回 409 提示用新版）；baseline/列表默认过滤 superseded。**迁移**：skill 加两列 + 存量行回填 version=1。③**I3 夜间全流水线一例**：预置画布跑一轮 → 评审门户对它做一次真实评审（approve）→ 验收记录。

**Tech Stack:** 1 迁移（review 表 + skill 两列）；前端零新依赖。

## Global Constraints

- C3：review 决策落库可审计；superseded skill 不物理删除（历史保留，v3 §29"不能覆盖旧版本"）。
- 破坏面控制：re-induce 语义变化影响既有测试（孤儿治理测试断言旧行被删）——按"测试即规格"逐个核对更新，语义变化（删→supersede）在测试注释中说明。
- 测试基线：224/27/29；仪式全流程。

---

### Task 1: I2 Skill 版本演化（TDD + 迁移）
- 迁移：review 表（后置建）+ skill 加 version Integer default 1 / superseded_by Integer nullable；存量回填 version=1。
- skill.py induce：不删删旧行——旧行 status="superseded"+superseded_by=新 id；新行 version=旧最大+1；断言/策略只写新行（旧行断言保留）。
- verify 端点：superseded 行 → 409 "该版本已被取代，请验证新版本"。
- baseline/audit/skills 列表默认排除 superseded（card 端点 404 对 superseded？——返回带 superseded 标记更友好，前端提示）。
- 测试：re-induce → 旧行 superseded 保留+新行 version+1；verify 旧行 409；列表不显 superseded；孤儿治理旧测试更新（语义：断言不再需要删——superseded 行保留断言作历史）。

### Task 2: I1 评审门户（TDD）
- models/迁移：Review 表。
- 端点 server/app/api/reviews.py：POST /reviews {agent_run_id, reviewer, decision, comment}（decision 枚举校验；同 run 重复评审 409）；GET /reviews?decision= 列表（含 agent_run 摘要 graph_name/status/画布名）；GET /reviews/{id}；GET /reviews/pending（未评审的 agent_run 列表——graph_name 前缀 canvas:/nightly 均含）。
- 前端 /reviews-portal：评审队列（pending 列表，点开看 node_outputs 的 review 摘要段）→ 评审表单三选一+评语 → 提交后进已评审列表。
- vitest：队列渲染/表单提交 body/已评审列表。

### Task 3: I3 夜间全流水线一例 + 仪式收尾
- 真库：预置画布跑一轮 → 评审门户 approve 一次（真实评审流）。
- 全量三套 → 审查 → 文档 → 浏览器实测（评审页截图 3+）→ 报告 → 合并。
