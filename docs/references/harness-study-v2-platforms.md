# 企业测试编排平台调研（2026-10-08，多 agent 学习第 3 路）

> 来源：MeterSphere v1.20.x-lts 官方手册 / TestRail 官方 / Katalon docs（一手）。
> Katalon TestOps 旧文档站已并入 True Platform，编排细节取自 Studio 维护中的套件/监听器机制。

## 一、MeterSphere（开源国产）

三层用例模型：功能用例（模块树 8 级/脑图视图）↔ 接口定义（定义↔用例一对多）↔ 场景（用例组装）。
场景步骤子结构三分类：**前置（脚本/SQL/等待）+ 后置（提取参数/SQL/脚本）+ 断言规则——
挂步骤级而非全局**。测试计划=跨类型容器（串/并行、独立/集合报告、资源池）。
**环境组**：跨项目场景一次选齐各项目环境。

**对 SkillLens**：chain 即"场景"；建议 chain 步骤 JSON 补 pre/post/assert 子结构位
（探针 verify 已是事实上的 post，规范化）；报告页学"总结→分节→失败明细→下钻"四层。

## 二、TestRail（失败分类的精髓）

**结果五态**：Untested（出过结果永不可回）| Passed | **Failed=跑了不符预期（产品缺陷）**
| **Retest=修了待重跑** | **Blocked=外部依赖阻塞根本没跑**。
三态正交：是否执行 × 责任在谁。**Blocked/Retest 驱动下一步动作而非布尔判定**，
统计上与 Fail 分开计。覆盖矩阵按"需求引用"组织。

**对 SkillLens**：与我们的 failure_class 设计直接互证。建议增加：
- `blocked`（环境/登录态失败、C1 未确认、链 fail 即停的后续步骤=没跑≠失败）
- `retest_pending`（自愈提案已生成待复验）
- **blocked 不进通过率分母**——直接提升趋势卡可信度

## 三、Katalon（钩子工程的关键细节）

- **按结果分叉的清理**：TearDownIfFailed / IfPassed / IfError——失败留现场供排查、
  成功清数据；**钩子失败不污染用例结果**（单独警告）
- Test Listener 全局生效先于 fixture，多监听器按字母序
- Execution Profile：环境×数据压成一个可切换变量集

**对 SkillLens**：AI5 teardown 采纳 `on: fail|pass|always` 条件 + cleanup 失败不计链 fail；
链模式步骤 checkbox 启停（临时禁用一步调试）。

## 四、复用与编排共性（三家横比）

MeterSphere 场景引用场景（引用关系可查可跨项目）+ **"查看引用"反向追溯**；
TestRail shared steps 集中存；Katalon 用例入多套件。
**精髓：复用单元是带反向引用可见性的一等公民——改一处知道影响谁。**

数据驱动：MeterSphere 场景变量五型（常量/列表/CSV/计数器/随机）。

**对 SkillLens**：①技能详情"被哪些链引用"反向列表（P2 superseded 跟新的前置）；
②链级 variables 最小数据驱动（在 ${unique:}/${stepN.x} 上加列表/CSV 型）。

## 五、权限与协作

MeterSphere 用户组=勾选式权限集；评审=对既有用例打通过/不通过+评论（结果标注流非状态机）；
Katalon AI 治理：AI 产出全程留痕"谁生成、谁批准、改了什么"。

**对 SkillLens**：技能晋升评审（candidate→learned）本质就是评审流的对象化（领先）；
补：驳回理由结构化、技能变更历史 diff 可见、reviewer 维度统计卡。

## 该抄的 Top5

| # | 项 | 价值 |
|---|---|---|
| 1 | TestRail 失败三态（Fail/Blocked/Retest 正交+Untested 单向） | failure_class 扩展，blocked 不进分母——趋势卡可信度 |
| 2 | Katalon 按结果分叉清理钩子（on:fail/pass/always+失败不污染） | AI5 teardown 具体形态 |
| 3 | MeterSphere 引用可见性（反向引用表） | P2 superseded 跟新的前置件，防连锁破坏 |
| 4 | MeterSphere 变量五型（+列表/CSV） | 链级最小数据驱动 |
| 5 | TestRail 指标口径一致性纪律 | 通过率/blocked/flaky 口径写入 arch 文档并版本化 |

Sources: metersphere.io/docs/v1.20.x-lts/user_manual/{test_track/*, api_test/*,
project_management/customcode_snippets}、docs.katalon.com/katalon-studio/*、
testrail.com/blog/*、support.testrail.com/*
