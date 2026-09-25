# Sprint 13 验收记录：Agent 运行时（块 F，M3 启动）

日期：2026-09-25。分支 sprint13-agent-runtime。
宪法 D4 里程碑：LangGraph 正式引入（langgraph 1.2.11 + langchain-core 1.6.3，pydantic 无冲突）。

## 验收结果

| # | 功能点 | 结果 | 真实证据 |
|---|---|---|---|
| F1 | LangGraph 底座 + 调度 | ✅ | 夜间三节点图（select→batch→aggregate）+ agent_run 全程落库；NIGHTLY_CRON 调度（默认 off） |
| F2 | Impact Analysis | ✅ | 真库：saveFormConfig 变更集 → **6 skill 全命中**，路径 `api:... → action:click:保存 → skill:N` |
| F3 | 批回放 | ✅ | browser 复用 + **C1 前置门控**（全 shadow 批零 launch，硬断言测试） |
| — | 夜间图实测 | ✅ | agent_run #1 finished：select 6 → 6 shadow run（零浏览器）→ aggregate shadow 6/6 |
| — | 三套测试 | ✅ | server **207**（192→207）/ extension 27 / web 23 |

## 审查与修复（仪式②价值）

- **C1 回归被抓**：T3 拆分使 shadow 单回放先开浏览器（违反 Sprint 4"shadow 绝不启浏览器"验收）→ 前置门控 `_shadow_run_if_gated` 修复 + 零 launch 硬断言；T3 写的断言回归行为的测试按"宪法即规格"修正。
- **真库 bug**：impact 双形态匹配键归并缺失（变体键 vs 裸键）→ 修复后 6 skill 全命中。
- **batch 前置清零 bug**：`runs = []` 会清掉 shadow 前置项 → 修复。
- 审查后顺手修：图节点改用 run_replay_batch（browser 复用 + 单 skill 错误不杀整晚，语义变更配双测试）；run_graph 异常先 rollback；scheduler 持 task 引用。

## 设计决策记录

- **夜间图错误语义**：图级异常→status=error；单 skill 异常→error run 继续（夜间回归一个坏 skill 不杀整晚）——审查修订，测试双覆盖。
- **uv.lock 镜像 URL**：langgraph 新增属合法变更，镜像 URL 哈希与官方一致，接受提交（AGENTS.md §四规则的例外，主线程决策）。
- 已知简化（审查非阻断记录）：shadow plan 空编译保真度、impact 全表扫描、混合批次顺序。

## Sprint 回顾（宪法 §12）

- #1 夜间工程底座（M3 主线）✓；#4 阶段纪律：按计划引入 LangGraph（D4 时点）✓。
- #5 C1：前置门控 + 零 launch 硬断言（加严方向）✓；#7 C3：agent_run 全节点产物落库 ✓。

## M3 进度

S13 ✅（块 F 全量）→ S14 编排画布（块 H）→ S15 晨间评审（块 I）；G 块（夜间开发）卡 G3 闸口。
