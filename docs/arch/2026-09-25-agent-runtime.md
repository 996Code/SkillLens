# Agent 运行时架构（S13，块 F）

> 夜间工程底座。宪法 D4：LangGraph 自此引入（MVP 期间刻意不用）。

## 组件

```
server/app/agents/
  runtime.py    夜间回归图（langgraph StateGraph，三节点线性）+ run_graph 执行器
  scheduler.py  NIGHTLY_CRON 调度（"off" 默认 / "nightly"=每天 02:00，asyncio 循环）

图：select_skills → replay_batch → aggregate
  select_skills  输入 change_set{api_templates, anchor_labels} → analyze_impact 选受影响 skill
  replay_batch   run_replay_batch 批量（C1 默认 shadow；全 shadow 零浏览器 launch；
                 单 skill 异常落 error run 不中断图——一个坏 skill 不杀整晚）
  aggregate      按 status 计数

执行记录：agent_run 表（graph_name/input/node_outputs[]/status/error_text）——
  C3：节点产物逐段 append 落库；图级异常 rollback 后收敛 status=error。
```

## Impact Analysis（learning/impact.py）

- 输入：变更集（api 模板 + 锚点 label）；输出：受影响 skill + 影响路径。
- 遍历：api 模板 →（calls 边反查，**双形态匹配**：裸模板 ↔ "POST:/x" 前缀形态，
  键归并回输入模板）→ action → skill 骨架签名匹配。
- 端点：POST /api/v1/impact/analyze、GET /api/v1/impact/last（最近夜间 agent_run）。
- 已知简化：skill 全表扫描（量级小可接受）；anchor 匹配为存在性校验。

## 批回放（replay/runner.py）

- POST /api/v1/skills/replay-batch {skill_ids, overrides_map, confirm_side_effect}。
- browser 实例复用：一次 launch，逐 skill 新 context；**C1 前置门控**
  （_shadow_run_if_gated）：shadow 项在开浏览器前判定落库，全 shadow 批零 launch
  （Sprint 4 验收语义保持）。
- 已知简化：shadow run 的 plan 以空 overrides 编译（记录保真度取舍）；
  混合批次结果顺序=shadow 前置项+execute 项。

## 依赖

langgraph 1.2.11 + langchain-core 1.6.3（uv add 引入，pydantic 2.13.5 无冲突；
uv.lock 含镜像 URL——哈希与官方一致，可复现性不受影响）。

## 真库验证（2026-09-25）

- impact：saveFormConfig 变更集 → 6 skill 全命中（共享保存流，路径正确）。
- 夜间图：agent_run #1 finished——select 6 → 6 shadow run（零 launch）→ aggregate shadow 6/6。
