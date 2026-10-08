# 2026-10-08 三轮全库评审 + 文档补全 验收记录

> 对应主计划 v2.3 条目。工作性质：全库审查+修复+文档建设（无新 UI 功能，
> 浏览器层实测以"工作台回归巡检"代替，见 §4）。

## 1. 评审产出

- 报告：`docs/reviews/2026-10-08-full-codebase-audit-round3.md`（七域并行深审；
  🔴 9 / 🟡 43 / 🟢 34；修复 53 项、缓修/记录 34 项逐条附理由与触发条件）。
- 修复全部 TDD：新增测试文件 server 5 个（schema_drift / role_gates / runner_watermark /
  executor_heal_gate / scheduler）+ extension 3 个（redact-parity / executor-injected-regex /
  capture-redact）+ web 3 个（AdaptersView / run-format / system-group）+ 既有 17 个测试文件用例增量。

## 2. 文档产出（用户要求"更新全部文档、补全缺失、更详细"）

| 文档 | 内容 |
|---|---|
| `docs/arch/2026-10-08-replay-engine.md` | 回放/执行引擎全链（时序/定位链/写水位/自愈两路径分歧/导出同源/债务/测试地图） |
| `docs/arch/2026-10-08-ingestion-pipeline.md` | 录制→学习数据管道（事件模型/采集纪律/上报幂等/派生流水线/归纳版本链/债务） |
| `docs/arch/2026-10-08-adapters-subsystem.md` | 适配器清单子系统（字段解剖/URL 匹配/探针/链编排/指纹/凭据脱敏与掩码回填/接入步骤） |
| `docs/arch/2026-10-08-auth-and-role-matrix.md` | 认证与角色矩阵（三层防线/97 端点矩阵/C1 确认门/token 生命周期） |
| `docs/arch/2026-10-08-redaction-defense-in-depth.md` | 脱敏纵深（六入口通道/防线地图/词表四处副本一致性/掩码回填/模板转义陷阱） |
| `docs/arch/2026-10-08-env-contract.md` | 环境变量契约（全部 env 权威清单——表外即违例） |
| `docs/arch/2026-10-08-change-intelligence.md` | 变更智能（ExpectedDelta 生命周期/classify 判定规则/影响分析/dev_plans 边界） |
| `docs/arch/2026-10-08-schema-migration-discipline.md` | 迁移纪律（双建库路径/drift 守卫/加列规程/已知债务） |
| `docs/references/project-lessons.md` | +9 条（#38-#46），更新记录至十二版 |
| `docs/specs/2026-09-24-master-delivery-plan.md` | +v2.3 条目（基线 server 546 / web 78 / extension 99） |
| `server/README.md` / `extension/README.md` / `server/web/README.md` | 鉴权契约升级、模块地图补全、共享模块与竞态守卫约定、词表纪律 |
| `PROJECT-GUIDE.md` / `docs/HANDOVER.md` | 三轮评审索引、基线更新、缓修项触发条件移交 |
| `deploy/README.md` | uv pin 0.8.4、njmind-state 仓库根路径（不再 /tmp） |

## 3. 三套测试终态

- server **546** passed（全量 20 分钟；起跑时与并行 pytest 撞 test.db 产生的 36E+11F
  已单独重跑证伪——15/15 过，lessons #43）
- web **78** passed
- extension **99** passed（11 文件；`npm run build` 产物含双写转义与 16 词词表已 grep 验证）

## 4. 浏览器层巡检（代替 UI 实测的说明）

本轮无新 UI 功能（除 AdaptersView select 失败防错——已由 `server/web/tests/AdaptersView.spec.ts`
覆盖 select 失败禁保存/busy 防重行为）。工作台交互回归依赖：web 78 例（含视图级 spec）+
server 546 例。**插件执行链行为未改动**（三处"路径激活型"修复明确挂起待真机矩阵轮，
见 HANDOVER §2），故未安排常驻浏览器矩阵重跑——下轮真机矩阵须连带验证：
① 首个定位步 8 次预算+reload 自愈（修复后激活）② Get Items 直调 CSRF（修复后激活）
③ hover-trigger 菜单校验（修复后激活）④ 本轮已修的页签复用收尾（about:blank 导航）
与失败调用留痕对录制的影响。

## 5. 提交

单分支 main 直提（评审轮惯例）：代码 34 文件 + 测试 24 文件 + 文档 14 文件；
`server/uv.lock` 镜像重写已还原；提交前红线自扫（`git grep 192.168` 空、
无 sk- 串、无明文凭据）。
