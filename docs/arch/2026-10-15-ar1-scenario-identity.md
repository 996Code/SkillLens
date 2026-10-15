# AR1：Scenario 身份收敛（管理平台闭环重构第一批）

> 2026-10-15 实施。规格：`docs/specs/2026-10-15-ar-management-closed-loop-redesign.md` §AR1。
> 本篇是落地后的架构契约——改场景/套件/评审相关模块前必读。

## 1. 身份与数据

- `chain` 表一次性改名为 `scenario`（迁移 `c4d2e6f8a0b1`），**ID 全部保留**（16 条）。
- `Scenario` 模型（`app/models.py`）：原 Chain 字段 + `status`(active/archived) +
  `definition_version`(乐观锁) + `origin`(manual/legacy_suite) + `updated_at`。
- 步骤 JSON 子引用键 `chain_id` → `scenario_id`（结构化逐键迁移，含显式 null；
  24 键全转换，downgrade 对称还原）。
- `test_suite` 补 `scenario_id/migration_status/migration_reason`：
  唯一存量 Suite 是 Odoo+ERPNext 混合系统 → 按规则记 `legacy_mixed_system`
  不猜测转换。同系统套件的确定性判定在 `app/scenario/migration.py::classify_suite_definition`
  （reuse=有序 Skill 序列与简单场景完全一致 / create / legacy_mixed / legacy_unknown）。

## 2. API 契约（AR1 后状态）

| 端点 | 行为 |
|---|---|
| `POST /api/v1/scenarios` | 创建（viewer 403）；返回 status/version/origin |
| `GET /api/v1/scenarios?system=&status=` | 列表（默认 active） |
| `GET /api/v1/scenarios/{id}` | 详情（steps 附 skill 概要：description/requires_confirmation/fill_fields） |
| `PATCH /api/v1/scenarios/{id}` | **If-Match: definition_version 必填**——缺头 428 / 过期 409(带当前版本) / 成功 version+1 |
| `POST /api/v1/scenarios/{id}/archive` | 归档（替代物理删除——有历史运行的场景不可销毁） |
| `POST /api/v1/scenarios/{id}/run?wait=1` | 过渡端点（AR2 将被 ScenarioRun 创建取代） |
| `GET /api/v1/skills/{id}/fills` | fill 候选（原 /chains/fills 迁移，路由序在动态段之前） |
| `GET /api/v1/skills/{id}/scenario-references` | 反向引用（原 /chains/references） |
| `GET /api/v1/suites[/{id}[/runs]]` | 只读审计（带迁移决策三字段） |
| `POST/DELETE /api/v1/suites*`、`POST /suites/{id}/run` | **410 冻结** |
| `POST /api/v1/expected-deltas/{id}/report` | **410 冻结**（AR4 由 ScenarioRun 终态自动生成） |
| `POST /api/v1/reviews` | **410 冻结**（AR4 评审对象改为场景报告）；GET 只读保留 |
| `/api/v1/chains*` | **JSON 404**（全局 /api/{path} 兜底——SPA fallback 不再吞 API 404） |

`main.py` 新增 `/api/{path:path}` catch-all：未知 API 一律 JSON 404，
机制化根治"SPA 兜底假绿"（UI 批2 发现的坑升级为全局防线）。

## 3. 调用方切换清单（AR1 后零残留）

- **server**：`app/api/scenarios.py`（新）/`app/replay/scenario_runner.py`（改名）/
  `app/scenario/`（新域服务包）；旧 `chains.py`/`chain_runner.py` 已删除。
  `adapters/manifest.py::Chain` 是 YAML 声明式业务链（另一套模型），**不改名**。
- **web**：`api.ts` Scenario 类型+`updateScenario(id, version, body)`（PATCH+If-Match）；
  ScenarioList/ScenarioDetail/GraphOverview/GraphWorkspace 全部切换；
  SuitesView 重写为 legacy 只读；ReviewPortal 去表单。
  `ScenarioDetail` 保存 409 时自动重载（防编辑过期快照）。
- **extension**：`shared/scenario-rules.ts`（改名，规则语义不变）；
  `executor-page.ts` `?scenario=`（TDZ 隐患顺手修：声明移到使用前）；
  `background/executor.ts` `runScenario`；`space-panel.ts` 全部端点+归档按钮；
  `uploader.ts` 消息协议 `scenarioId`。
- **scripts**：chain_regression/s45_*/an_snipe_record/ai2_* 全部切换。

## 4. 迁移与回滚纪律

- 副本验证顺序：upgrade → 断言（16 行/24 键/迁移决策）→ downgrade → 断言（16 行/24 键还原）→ upgrade。
- 生产已应用（2026-10-15）。**AR2 产生 ScenarioRun 后**：回滚=只回代码不 downgrade
  删新表（规格 §8.4 expand→切流→contract）。
- `alembic downgrade` 只用于空库/副本验证。

## 5. 测试与验收记录（2026-10-15）

- server：新增 `test_scenarios_api.py`（10 用例：CRUD/版本三态/归档/旧路由 404/
  角色门/冻结端点 410）+ `test_scenario_suite_migration.py`（4 用例确定性判定）；
  `test_chains_api.py` 删除（由前者覆盖）；`test_chain_*.py` 迁移为 Scenario 语义。
- web：SuitesView/ReviewPortal spec 重写为只读契约（含"零写请求"断言）。
- extension：147 全绿（chain-rules → scenario-rules 改名）。
- 真机：API 三态（428/409/200）+ 编辑闭环（改名→DB 落库→version 1→2→3→还原）+
  executor.html `?scenario=6` 场景数据拉取 + legacy Suite/评审只读页。
- 生产基线：16 Scenario / 24 scenario_id 键 / suite=legacy_mixed_system。

## 6. AR2 衔接点

`app/scenario/service.py`（待建）将消费：Scenario.definition_version（快照根版本）、
`expand_steps`（闭包展开基础已在 scenario_runner.py）、`classify_suite_definition`
（SuiteRun 历史回填复用）。PATCH 的 If-Match 语义即 ScenarioRun 创建时的版本定格来源。
