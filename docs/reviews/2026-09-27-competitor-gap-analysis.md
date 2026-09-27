# 对标差距分析（2026-09-27）

> 触发：用户方向指令——"我们对标那几个系统的差异缺失了，好好规划规划"。
> 结论已进主计划 v1.6（块 S/T/V/U/W + X 暂缓 + 明确不做项）。
> 基准：产品宪法 §11 调研（2026-09-23）+ 本次联网核实（2026-09-27）。

## 一、新情报（相对 09-23 调研的变化）

| 情报 | 影响 |
|---|---|
| UiPath 2026-09-26 发布 agentic 性能测试进 Test Cloud | 性能维度被巨头占位——我们以"性能漂移进四分类"低成本跟进（块 V） |
| QA Wolf 2026 横评提出执行模型二分法：确定性代码 vs 运行时解释 | 印证我们"LLM 提案、确定性判定"路线站在正确一侧 |
| QA Wolf AI 维护代理：诊断失败根因→更新测试代码 | 自愈闭环（块 U）是 table stakes |

## 二、差距矩阵（它们有 → 我们缺）

| # | 能力 | 谁有 | 我们现状 | 裁决 |
|---|---|---|---|---|
| 1 | 团队协作/多用户权限 | 商业平台标配 | 无登录、单用户 | **块 S**（G4 前置，最高优先） |
| 2 | 视觉回归 | Applitools/Percy/Mabl | 有快照存档、无比对引擎 | **块 T** |
| 3 | 自愈定位 | Testim/Mabl/Functionize | 5 级 fallback 定位，失败即终止 | **块 U** |
| 4 | 性能测试 | UiPath（09-26 新发） | duration_ms 已采集、无基线判定 | **块 V**（边际成本低） |
| 5 | CI/CD 与外部集成 | Mabl/QA Wolf | 零集成 | **块 W** |
| 6 | 测试代码导出 | QA Wolf（NL→Playwright 进仓库） | 仅内部执行 | **块 W1** |
| 7 | 失败根因 AI 诊断 | QA Wolf/Functionize | 有归因（replay_failure_attribution）、无修复动作 | **块 U3** |
| 8 | Flaky 过滤/自动重跑 | QA Wolf | 事后一致性统计、无执行时重跑 | **块 U2** |
| 9 | DB 级副作用验证 | QA Wolf | API 层为止 | **块 X 暂缓**（试点反馈后定，需 G7 DB 只读授权） |
| 10 | 跨浏览器/移动端/无障碍 | Testim/Mabl/QA Wolf/Applitools | 仅 Chromium | **明确不做** |

## 三、独有优势（无人做，守住）

1. Evidence Graph + 四分类报告（需求预期 vs 实际）——全赛道无人做，差异化核心
2. 真实后端验证——Meticulous 回放 mock 网络，我们验真实 API 状态
3. 架构级数据不出网（私有化默认）
4. C1 影子纪律 + 证据晋升（candidate→learned→validated）
5. Skill 版本演化 + 跨系统通用层（槽位映射）
6. 证据回查的流程生成（Katalon 凭空生成，我们每步有证据引用）

## 四、执行顺序与依据

S（G4 硬前置）→ T（断言最大盲区，演示价值高）→ V（数据已在采集，抢叙事窗口）→ U（table stakes，宪法边界内做）→ W（进团队工作流）→ X（视试点）。

## 来源

- QA Wolf: The 12 Best AI Testing Tools in 2026 — https://www.qawolf.com/blog/the-12-best-ai-testing-tools-in-2026
- UiPath agentic performance testing — https://www.uipath.com/platform/agentic-testing/performance-testing
- UiPath: The dark testing factory — https://www.uipath.com/blog/ai/dark-testing-factory-continuous-testing-finally-realized
- Katalon 2026-05 更新 — https://blog.csdn.net/oscar999/article/details/162077496
- 产品宪法 §11（2026-09-23 调研存档）
