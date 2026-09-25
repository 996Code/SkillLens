# S10.5 验收记录：链路审计（主计划块 M，C3 可视化）

日期：2026-09-25。分支 sprint10p5-audit-view。
来源：主计划 v1.3 块 M（审查报告 G-1）。

## 验收结果

| # | 功能点 | 结果 | 证据 |
|---|---|---|---|
| M1 | 会话链路下钻 | ✅ | /audit 四区块 + trace 六段（窗口→语义动作→对齐→Skill→回放）；真库 42 会话实测 |
| M2 | 证据图视图 | ✅ | type/src_like 过滤，计数倒序；contains 过滤后 calls 零残留 |
| M3 | LLM 调用日志 | ✅ | 200 字摘要（写入侧 URL 脱敏不被读取截断绕过——审查确认）；行展开 |
| M4 | 噪声过滤决策视图 | ✅ | trace 每窗 kept/reason（管道 orphan_click + 手插 read_only 双测试） |
| — | 三套测试 | ✅ | server **172**（165+7）/ web **21**（17+4）/ extension **24** |
| — | 代码审查 | ✅ | 无阻断；4 项低成本修复已做（limit ge/le 校验、Alignment 列裁剪、trace 竞态守卫、App 导航断言规格修正） |
| — | 用户层实测 | ✅ | demo/sprint10p5/user-test-report.md + 4 截图（零控制台错误） |

## 设计取舍（审查 #3）

trace 的语义动作区展示快照 **forms 计数概要**；快照明细走既有 `/sessions/{sid}/semantic-actions` 端点（UI 入口列入后续迭代）。理由：trace 单请求聚合六段，快照全文会撑爆响应体（22 字段 × 2 相位）。

## 过程记录

- 审查发现 limit=-1 在 SQLite 语义为"不限制"→ 已加 Query(ge=1, le=1000)。
- Alignment 全表扫描（含大 JSON 反序列化）→ 列裁剪为 id/session_ids/skeleton/buckets。
- 真库 19 会话 filtered_count 全 0——真实流量全通过噪声过滤，kept=false 路径由测试覆盖（符合预期：njmind 操作流无纯浏览窗）。

## Sprint 回顾（宪法 §12）

- #1 主链路（评审载体）✓；#7 C3 审计界面补齐 ✓；#9/#10 客观达成（172+21+24 全绿，验收表逐条证据）✓。
