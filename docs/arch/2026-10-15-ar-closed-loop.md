# AR：管理平台闭环——架构契约（AR1-AR6 全量）

> 2026-10-15 落地。规格：`docs/specs/2026-10-15-ar-management-closed-loop-redesign.md`；
> AR1 细节另见 `docs/arch/2026-10-15-ar1-scenario-identity.md`。改场景/运行/报告/评审模块前必读。

## 1. 主链（本块之后的产品主干）

```text
Scenario（用户工作层，版本化定义）
  → ScenarioRun（一次执行：闭包快照+期望快照+幂等键+C1 定格）
    → ReplayRun ×N（execution_index 有序挂靠，attempt 重试不覆盖）
      → ScenarioReport（终态自动生成，一 run 一报告）
        → ReportDelta ×N（expectation_key 防重的四分类明细）
          → ReportReview（一报告一评审，决策不可变）
```

模块地图：`app/scenario/`（service=闭包/幂等/执行；migration=Suite 判定）、
`app/reports/`（service=快照/生成/收割）、`app/api/scenarios.py`+`scenario_runs.py`
+`reports.py`（AR4 段）+`reviews.py`（pending=报告队列）。

## 2. 关键不变量（破坏即回归）

1. **闭包不可变**：运行只读 definition_snapshot（root 版本+每层 source_path 版本），
   场景后续编辑不影响历史运行；重复引用子场景靠 source_path occurrence 区分。
2. **期望随运行定格**：expectation_snapshot 只在建 run 时生成；改绑/改期望内容
   不改变历史报告；expectation_key=sha256(canonical(occurrence/version/delta))。
3. **C1/C2 父锁**：confirm_side_effect/source_track 唯一事实源=ScenarioRun；
   插件 plan 带冲突 confirm → 409。写判定=骨架签名 ∪ label 词表
   （`app/scenario/service.py::_skill_writes`——经典表单录制盲区兜底）。
4. **计数服务端推导**：finish 时按每 execution_index 最高 attempt 汇总；
   blocked=快照步数−已执行；blocked 不落占位 ReplayRun。
5. **幂等三层**：Idempotency-Key 全局唯一（DB 约束兜底并发）+请求指纹
   （同键异请求 409）+终态不可变（同终态重放 200/冲突 409）。
6. **无期望≠无异常**：报告恒为 ready+coverage_state=no_expectation；
   generation_failed 显式可 retry（同报告 upsert，不产第二份）。
7. **历史不猜**：3115 旧 run=legacy_unscoped；混合系统 Suite=legacy_mixed_system；
   失败分类无证据=保留 None（回填不猜 e4）。

## 3. API 面（AR 后全量）

| 域 | 端点 |
|---|---|
| 场景 | POST/GET /scenarios；GET/PATCH /scenarios/{id}（If-Match）；/archive；/references |
| 期望 | POST/GET /scenarios/{id}/expectations（confirmed 才可绑；部分唯一索引） |
| 运行 | POST /scenarios/{id}/runs（Idempotency-Key）；GET /scenario-runs[/{id}]；/finish |
| 报告 | GET /scenario-runs/{id}/report；GET /scenario-reports；POST /scenario-reports/{id}/retry |
| 评审 | POST /reports/{id}/review（report_review 表）；GET /reviews/pending（=ready 未评审报告） |
| 冻结 | 旧 /chains 404；Suite 写/旧手工报告/AgentRun 评审写 410 |

## 4. 前端信息架构（AR5 后）

导航五区：测试场景 / 运行与问题（场景运行+时间线+失败分析）/ 报告与评审 /
步骤库（默认收起）/ 系统与环境。开发者工具（学习图/画布/审计/旧报告/字段类型/
legacy 分组）默认收起。总览指标含"场景运行通过率"（终态口径）。
页面：ScenarioRunsView / ScenarioRunDetail / ScenarioReportsView（评审同屏）。

## 5. 插件执行（AR3 后）

executor.html `?scenario=<id>`：先 POST /scenarios/{id}/runs（C1 服务端短路
shadow）→ 逐步 runSkill 带 scenario_ctx（plan 三闸校验）→ finish 父运行
（abort 语义含用户停止）。`api()` 已修 headers 合并（自定义头不再被覆盖）。

## 6. 回填与数据状态（2026-10-15 生产）

- scenario 16（ID=原 chain）；suite 1=legacy_mixed_system。
- replay_run：3115 历史行 scope_kind=legacy_unscoped；新行挂 scenario_run_id。
- 失败分类：1768 fail/error 中未分类仅 37（2.1%——真无证据）。
- scenario_run 9 条（AR 验证期产物）；scenario_report 1 份（已评审）。

## 7. 后续衔接

- 场景详情页期望绑定 UI + 运行按钮直连 ScenarioRun 创建（Web 侧两处接线）。
- AP 零仪式录制：产出进"待发现"——复用 Scenario 创建（origin=learned）。
- 陈旧 generating 收割器需定时触发（当前 lazy：下次 finish/重试时顺带）。
