# Harness 学习 v2：五路调研汇总与落地路线图（2026-10-08）

> 五路并行调研归档：zcode 二次深读 / Playwright 深层 / Cypress 调试体验 /
> 企业编排平台 / AI 自愈产品（见 harness-study-v2-*.md 五份）。
> 本文是汇总：交叉验证结论 + 统一落地路线图（含异常分类学设计的最终形态）。

## 一、五路交叉验证的关键结论

### 1. 失败分类是行业的共同答案（三路独立互证）

- **TestRail**（产品层）：Fail/Blocked/Retest 三态正交——"是否执行 × 责任在谁"，
  Blocked 不进通过率分母，Retest 驱动下一步动作
- **阿里云 quarantine 流水线**（工程层）：STABLE/FLAKY/BROKEN 按重跑结果判定；
  BROKEN 不进隔离区；**主干禁止自动重跑**（统计纯度）
- **我们自己的实锤**：42% 失败率里 E1 环境/E2 基础设施混在"链失败"里——若依 3 连败
  全是登录态（环境），不是链坏了

**结论：异常分类学（E1-E4 + blocked/retest/flaky_verdict）必须做，且口径业界成熟。**

### 2. 我们的领先点（业界对照后确认，应保持并大声说）

1. **自愈三层链**（LLM 提案→确定性 locate 验证→verify 计数晋升）比 mabl 单次通过
   即入库证据更厚，比 VON Similo 论文方案（实证 +42.9% 但无防回归闸）多验证闸
2. **supersede 版本链**业界独有——自愈产生可审计可回滚的技能演化史
3. **全链路证据落库**（C3）+ 证据驱动确定性判定——比 Testim 静默自愈透明
4. 声明式零代码接入（适配器清单）+ 本地自托管

### 3. 最值得抄的机制（按出处归并）

| 机制 | 出处 | 我们对应物 |
|---|---|---|
| 断言软收集（全量执行不中断，run 末统一判） | Playwright expect.soft | assertion_results 结构天然适配 |
| retain-on-failure 证据策略 | Playwright Trace | observed/截图链 |
| 步骤-事件交织时间线 + 命令日志数据 API | Cypress Command Log/tap | executed+observed 交织落库 |
| 断言有界重试+重试计数披露 | Cypress retry-ability | settle 语义扩展到断言层 |
| 按结果分叉清理钩子（on:fail/pass/always） | Katalon TearDownIfFailed | AI5 teardown 的具体形态 |
| 元素历史版本表+回滚 UI | mabl | supersede 链（比它强，缺呈现） |
| 置信度面板+低置信不晋升 | mabl Find Summary | verify 计数+LLM 归因理由 |
| 属性权重预筛+LLM 精选两段式 | Healenium+VON 论文 | 提案排序加确定性预筛层 |
| 错误三码+行动指引消息 | zcode | E1-E4 签名表 |
| 引用可见性（反向引用表） | MeterSphere | 技能被哪些链引用 |
| 变量五型（列表/CSV） | MeterSphere | 链级最小数据驱动 |
| 指标口径一致性纪律 | TestRail | 趋势卡口径写入 arch 文档 |

## 二、统一落地路线图（块 AJ：异常分类学与证据体验）

### AJ1 失败分类地基（P0，半天）
- `ReplayRun.failure_class`（e1_env/e2_infra/e3_drift/e4_expected/null）+
  `flaky_verdict`（stable/flaky/broken，趋势层算）+ 迁移
- 分类器纯函数（规则表：登录特征 URL/chrome-error/Token额度串/定位 miss/断言 fail）
- **E1/E2/blocked 不进通过率分母**；链 fail 即停的后续步骤标 blocked 非 fail
- zcode 错误三码+行动指引消息格式

### AJ2 登录守卫（E1 首实例，P0）
- 步骤证据 URL 命中 login 特征 → 判"登录态丢失"，不烧介入额度
- 自动恢复：适配器登录例程（服务端已实现）→ 从当前步重试
- run 记 `session_recovered` + 恢复次数

### AJ3 证据体验升级（P1）
- executed[] 对齐 TestStep（category/时间/附件引用/步内网络事件引用）
- run 详情页交织时间线（编号步骤+灰色事件条）+ 每步语义快照悬停
- 断言软收集+有界重试+重试计数
- retain-on-failure：成功只留摘要，失败保留完整证据链

### AJ4 自愈透明度（P1）
- 晋升 diff 视图（旧标签→新标签+归因理由）
- 置信度面板（verify 明细+LLM 理由），低置信只告警
- supersede 链一键回滚 UI
- mabl 持久化门控：verify 外加"下游步骤成功"证据位

### AJ5 编排增强（P2）
- Katalon 式清理钩子（on:fail/pass/always）
- 链步骤 checkbox 启停；反向引用表；链级变量五型（列表/CSV）
- 提案排序 Healenium 权重预筛（LLM 只精选 Top-N）

## 三、指标口径纪律（TestRail 教训）

通过率/blocked/flaky/漂移率口径一经定义写入 `docs/arch/` 并版本化——
**同一指标同一口径跨所有发布，历史卡不因口径变更失真**。
