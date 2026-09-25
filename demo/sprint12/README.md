# Sprint 12 学习深化验收记录（块 N）

日期：2026-09-25。分支 sprint12-learning-deepening。
输入：S11 三机制边界实证（回放路径外不可见/页载 GET 不可见/label 消歧不足）。

## 验收结果

| # | 功能点 | 结果 | 真实证据 |
|---|---|---|---|
| N1 | 新功能增量发现 | ✅ | 真实查询操作 → **2 项 discovery 自动落库**（/codeBack/formConfig/pageList 新 API + "查询"新锚点，status=new）；GET /discoveries 端点 |
| N2 | Requirement 先验对齐 | ✅ | confirm delta 7 → **2 项自动 linked**（linked_delta_id=7）；报告页"已发现实现 ×2"徽标（截图 01） |
| N3 | Outcome 层1 toast 采集 | ✅ | 插件 collectToasts（≤3×100 字符/敏感词整条丢弃）；server toast 信号→断言→**回放评估三态**（快照命中 PASS/未命中 FAIL/无快照 skipped）；回放侧 page_snapshot 同步采 toasts |
| N4 | 层4/5 | ✅ | 层4：verify 3 次通过 → layer4_verified，**重建断言不清零**（资产语义）；层5：consistency 端点真库验证（skill 7：4 断言 × 3 run 全一致，截图 02） |
| N5 | Active Probing 设计 | ✅ | docs/arch/2026-09-25-active-probing-design.md（三段式循环 + G6 闸口） |
| — | 三套测试 | ✅ | server **192**（172→192）/ extension **27**（24→27）/ web **23**（21→23） |

## 审查与真机修复（仪式价值实证）

- 审查阻断项：toast 断言回放恒 FAIL（评估器从响应体取 toast 字段永不可得）→ 修复为快照 toasts 通道 + 三态测试。
- 真机 bug ×2（单测全绿但真库/真机暴露）：
  1. consistency 匹配键依赖 kind，而 assert_eval 结果行**不含 kind** → 真库零匹配；修复为 (api_template, field_key) 匹配 + 真形态回归测试。
  2. **dist 重建废已加载扩展**（CS 引用旧 hash 文件 404 → 静默零采集）→ lessons #17；任何 build 后须重启常驻浏览器。
- 真库迁移遗漏（evidence_count 列未跑）→ 500，upgrade head 修复。

## N1/N2 与 S11 边界的闭环

S11 发现"回放路径外新功能不可见"→ N1 现在能**发现**它们（discovery 表）；N2 让需求确认时**自动对齐**已发现实现。四分类的 missing 语义从此有了行动出口：missing 项先查 discoveries——已发现→实现存在只是不在回放路径；未发现→真缺失。

## Sprint 回顾（宪法 §12）

- #1 主链路（学习能力深化）✓；#7 C3：discovery/计数/一致性全落库 ✓；LLM 零新增调用（N1 v1 纯确定性）✓。
