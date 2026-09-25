# S15 用户层闭环测试报告（评审门户 + Skill 演化）

日期：2026-09-25。环境：8710 server（S15 代码）+ 真库（5 个 agent_run 待评审）。

## 评审门户（/reviews-portal）

| # | 测试项 | 界面设计 | 功能可用性 | 证据 |
|---|---|---|---|---|
| 1 | 评审队列 | ✅ 队列+已评审双区，与 Reports 导航区分清晰 | ✅ 5 行渲染（真库 canvas/nightly run） | 截图 `01-review-portal.png` |
| 2 | 展开评审表单 | ✅ 三选一单选（通过/驳回/打回）+ 评语 | ✅ 3 单选渲染；夜间摘要 markdown 提取（修复：画布节点 n5 的 output.review 键统一提取） | 截图 `02-review-form.png` |
| 3 | 真实评审流 | — | ✅ API 实测：画布运行→队列→approve 201→队列减一 | demo/sprint15/README.md |
| 4 | 徽标 | ✅ approved 绿徽标 | ✅ | 截图 01 |
| 5 | 控制台 | — | ✅ 零页面错误 | console 监听 |

## Skill 演化（用户可见面）

- 列表/基线/审计默认不显 superseded（历史版本不干扰日常工作）✓
- 详情页 superseded 提示（"该版本已被 vN 取代"）已补 ✓

## 易用性发现

| # | 严重度 | 问题 | 处置 |
|---|---|---|---|
| U9 | 低 | pending 无分页（agent_run 增长后变重） | 审查记录，后续加 limit |
| U10 | 低 | 评审队列含 status=started 的运行中 run | 后续过滤 |

**结论：测试通过。**
