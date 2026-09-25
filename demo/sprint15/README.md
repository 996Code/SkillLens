# Sprint 15 验收记录：晨间评审 + Skill 演化（块 I，M3 可自主段收尾）

日期：2026-09-25。分支 sprint15-review-evolution。

## 验收结果

| # | 功能点 | 结果 | 证据 |
|---|---|---|---|
| I1 | 评审门户 | ✅ | /reviews-portal：队列/三选一表单/已评审徽标；真库闭环（画布运行→approve 201→队列减一）；截图 2 张 |
| I2 | Skill 版本演化 | ✅ | re-induce 不删旧行：v1(superseded)→v2 链式；断言/策略历史保留；verify/replay/observe/assertions 四端点统一 409；列表五处过滤；详情页 superseded 提示 |
| I3 | 夜间流水线一例 | ✅ | 预置画布运行→评审门户 approve——M3 可自主段出口验证 |
| — | 三套测试 | ✅ | server **232**（224→232）/ web **34**（29→34）/ extension 27 |

## 审查与修复

- 合并前修 3 项：superseded 执行面统一（replay/observe/assertions 加 409，与 verify 同口径）；review.agent_run_id DB 唯一约束（迁移修订 + downgrade/upgrade 实跑应用）；前端消费 superseded_by（SkillCard 类型+详情页提示）。
- 真机修复：评审摘要 markdown 提取（夜间图节点名 review_output vs 画布节点 n5——统一按 output.review 键提取）。
- 已知简化（转后续）：pending/reviews 无分页；started 状态 run 进队列；evidence_edge 计数语义（同步次数非去重证据）文档注记；GET /reviews/{id} 计划偏差未实现。

## 语义变更记录（测试即规格）

- induce"删旧建新"→"supersede 链"：孤儿治理测试改写（旧行保留/409/版本链），v3 §29"不能覆盖旧版本"落地。
- SQLite rowid 复用差异（旧语义新行复用被删 id）随语义变更消失。

## Sprint 回顾（宪法 §12）

- #1 M3 可自主段收齐（F/H/I）✓；#7 C3：superseded 不物理删除、review 决策落库 ✓。
- M3 完整出口（夜间自动开发+测试+评审）仍卡 G3 闸口（njmind 开发自动化授权）——当前达成"定向回归+评审"半闭环。
