# Sprint 13 Agent 运行时 Implementation Plan（块 F，M3 启动）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划块 F。前置：evidence_edge/discovered_feature/skill_strategy 已就绪（S10/S12）。

**Goal:** 夜间工程的运行时底座——LangGraph 引入（宪法 D4：Phase 3 才引入，现在到了）、Impact Analysis（版本 diff→图遍历→受影响 Skill→定向回归清单）、回放并发。

**Architecture:** ①**F1 LangGraph 底座**：引入 langgraph 依赖；`server/app/agents/` 目录——`runtime.py`（graph 构建器：节点=可调用步骤，边=数据流；v1 图=「select_skills → replay_batch → aggregate」三节点夜间回归图）+ `scheduler.py`（cron 驱动：APScheduler 或简易循环线程，v1 用 asyncio 循环 + env NIGHTLY_CRON 表达式默认关）；执行记录落 `agent_run` 表（graph 名/输入/节点产物 JSON/status/started/finished）。②**F2 Impact Analysis**：`server/app/learning/impact.py`——输入变更集（api 模板列表/ui 锚点列表，来源：discovered_feature 或 delta changes），沿 evidence_edge 图遍历（变更→calls/contains 边→关联 action→关联 skill 的骨架签名），输出受影响 skill 清单 + 每项影响路径；端点 `POST /api/v1/impact/analyze`（body: {api_templates, anchor_labels}）+ `GET /api/v1/impact/last`。③**F3 回放并发**：runner 支持批回放 `POST /api/v1/skills/replay-batch`（skill_ids 列表，串行 v1——但 browser 实例复用：一个 browser 多 context 顺序执行，避免 profile 锁；并发度 env 可配默认 1）；agent 图的 replay_batch 节点调用它。④**夜间图实测**：用 impact 结果驱动定向回归（只回放受影响 skill）全链跑一次。

**Tech Stack:** langgraph + langchain-core（uv add）；APScheduler 不引入（asyncio 循环够 v1）；1 迁移（agent_run 表）。

## Global Constraints

- C1：批回放每 skill 仍走 requires_confirmation 门控（batch 默认 shadow，confirm_side_effect 批级参数）。
- C3：agent_run 全节点产物落库。
- LLM 边界：本 Sprint 零 LLM 调用（图是确定性编排）。
- 测试基线：192/27/23；仪式全流程。
- langgraph 若与现有依赖冲突（pydantic 版本等），降级方案：自研极简 DAG 执行器（节点=async fn，串行执行+产物传递），功能等价、零新依赖——实施时评估，报告里说明选择。

---

### Task 1: F1 LangGraph 底座 + agent_run 表（TDD + 迁移）
- uv add langgraph langchain-core（评估兼容性；冲突则走降级方案）。
- 迁移：agent_run 表（id/graph_name/input JSON/node_outputs JSON/status started|finished|error/started_at/finished_at/error_text）。
- agents/runtime.py：`build_nightly_graph()`——三节点：select_skills（输入：变更集或全量；调 impact）→ replay_batch（批回放）→ aggregate（汇总 pass/fail 写回 node_outputs）；`run_graph(db, graph_name, input) -> AgentRun`（执行全程落 agent_run，节点产物逐段 append）。
- agents/scheduler.py：`start_nightly_scheduler()`（asyncio 循环，NIGHTLY_CRON env "off" 默认；每 tick 跑夜间图）；main.py 启动时按 env 拉起。
- 测试：graph 执行（FakeProvider 环境）三节点产物落库；error 节点→status=error。

### Task 2: F2 Impact Analysis（TDD）
- learning/impact.py：`analyze_impact(db, api_templates, anchor_labels) -> {affected_skills: [{skill_id, name, paths: [边序列]}], unchanged_count}`——evidence_edge 遍历：api 模板→calls 边反查 action→contains 边反查 session→alignment（session_ids 含）→skill；anchor 同理。纯查询。
- 端点 POST /impact/analyze + GET /impact/last（最近一次 agent_run 的图输入输出）。
- 测试：造 evidence_edge+skill → 变更集含 saveFormConfig → 受影响 skill 命中且路径正确；无关变更 → 空。

### Task 3: F3 批回放（TDD）
- POST /skills/replay-batch {skill_ids, overrides_map?, confirm_side_effect=false}——循环单 skill run_replay（browser 实例复用：一次 launch 多次 context）；结果聚合 {results: [{skill_id, run_id, status}]}；C1：confirm_side_effect 批级。
- 测试：两 skill 批 shadow → 两 run 落库 mode=shadow；批 execute（FakePage 替身）→ 串行执行产物齐全。

### Task 4: 夜间图实测 + 仪式收尾
- 真库跑一次夜间图（输入=发版2 变更集 → impact 选中 skill 7 → 批回放 shadow → aggregate）。
- 全量三套 → 审查 → 文档（agents 架构契约）→ 浏览器实测（impact 端点 curl + agent_run 审计呈现——audit 页加 agent_run 区块或 API 截图）→ 报告 → 合并。
