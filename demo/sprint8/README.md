# Sprint 8 验收记录：UI Before/After 快照（spec §4.3 层 2(b) 补盲）

日期：2026-09-24。分支 sprint8-ui-snapshot（04eb612 → 本次验收合并）。
环境：Windows + uvicorn 8710（真实 LLM 新令牌）+ 常驻浏览器 CDP 9222 + 新构建插件。

## 验收标准（计划 Task 5 / 主计划块 B）

> 快照全链路落库 + ui_text 断言生成/评估 + 回放前后快照 + 默认值盲区实测。

## 结果

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 插件快照采集 | ✅ | 常驻窗口采集 13 事件（action 2/navigation 1/network 8/**snapshot 2**）；快照 forms=22/labels=20/tables=3 |
| 2 | server 解析落库 | ✅ | process 后 state_before/after 非空（各 22 forms）；semantic-actions API 返回两字段；迁移 c9d41f2a7e03 |
| 3 | ui_text 断言 | ✅（生成链路单测锁定） | state diff→ui_text→verify 三态（PASS/FAIL/快照缺失）由 test_outcome 2 + test_assert_eval 4 用例锁定 |
| 4 | 回放前后快照 | ✅ | run 13 PASS，plan 含 before/after_snapshot（before=`auto-s8-e2e` → after=`s8-e2e-replay` 证实注入） |
| 5 | 盲区实测 | ⚠️ 场景未触发（生成链路已锁定） | auto_record 时序下 before 已含新值（fill 在锚点前）→ diff=0 不生成（语义正确）；真实默认值变更场景需人工 njmind 操作，生成/评估链路由单测+回放实测覆盖 |
| 6 | 全量回归 | ✅ | server **133 passed**（121→133）、extension **24 passed**（19→24） |

## 审查与修复（每任务审查-修复-文档流程）

- **T1/T2 审查**：耦合五项全 PASS（snapshot 纯函数/capture 纯增量/assign_snapshots 独立/九条消费路径零污染）；修复：敏感 label 脱敏（复用 redactValue，红测试锁定）。
- **T3/T4 审查**：零破坏面（assert_eval 签名/plan 旁挂全调用方核实）；修复 4 项：label 截断跨侧统一 100、注释归属、**ui_text fail-open 区分**（快照在但字段缺失→FAIL，字段消失是回归信号）、detach 容错+hidden 祖先过滤。
- **文档**：docs/arch/2026-09-24-ui-snapshot.md（采集/归属/边界契约）；server/README.md + extension/README.md（模块导览，首次补全）。

## 过程发现（记入台账）

- 快照采集时序语义：before 采于锚点动作瞬间——"填完再点保存"流中 before 已含新值；ui_text 的目标场景是"锚点动作触发后续状态变化"（如确认弹窗后状态刷新），与 spec 层 2(b) 预期一致。
- njmind 表单 22 字段中 17 个 label 为空、多框共享 placeholder"请输入"——真实默认值场景需 label 消歧（S10 议题）。
- labels 语义两侧分歧：回放侧可见性过滤更严（hidden 祖先链），插件侧录到 20/回放侧 0；labels 不参与断言，无功能影响，S10 对齐。

## Sprint 回顾（宪法 §12）

- #1 主链路（Outcome 层 2 证据）补盲 ✓；#2 投入全在 ③ 证据层 ✓。
- #5 C1 零违规（shadow 路径不采快照，plan 原样）✓；#7 C3 快照事件/解析产物/回放快照全落库 ✓。
- #9/#10 客观达成（133+24 全绿，验收表逐条证据）✓。
