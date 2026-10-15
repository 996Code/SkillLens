# AR 块：管理平台闭环重构（Scenario → Run → Report → Review）

> 日期：2026-10-15  
> 状态：**已立项、待实施**  
> 触发：AQ 信息架构复盘。AQ 将测试场景提升为用户工作层，但只完成展示与导航；
> 场景运行、报告、评审、证据仍分属 Chain / ReplayRun / AgentRun / DeltaReport 多条孤立链。
> 本文是 AR 的唯一实施规格；范围与顺序变更须先改主计划 §7。

## 1. 问题与目标

### 1.1 原始产品闭环

SkillLens 不是通用脚本管理器。目标是从真实业务操作中学习流程与正常结果，并持续回答：

1. 应该变化的是否已经变化；
2. 不应该变化的是否被破坏；
3. 业务结果是否正确；
4. 结论是否有可追溯证据。

目标用户路径：

```text
采集/任务切分 → 人工确认 → 测试场景 → 场景运行
→ 失败/漂移证据 → 自动变更报告 → 人工评审
```

AR 负责从“测试场景”开始贯通后半段；AP 零仪式录制负责前半段，仍按独立设计推进。

### 1.2 当前事实（2026-10-15 主库）

| 对象 | 数据 | 结构问题 |
|---|---:|---|
| Chain（UI 称测试场景） | 16 | 无聚合运行实体；状态用链首 Skill 最新 run 近似 |
| ReplayRun | 3115 | 只知 skill，不知属于哪个场景/第几步 |
| Timeline | 3115 run + 925 session | 数据充足，但主对象仍是 Skill |
| Learning Graph | 925 session / 2065 window / 1579 action | 有数据但只是诊断视图，未挂到场景/运行 |
| Audit | 1723 evidence edge / 1740 LLM log | C3 完整，但属于开发者资产 |
| Canvas | 2 canvas / 1 agent run | 与场景链、插件执行分裂 |
| Expected / Observed Delta | 9 / 17 | 有原料，无自动报告主链 |
| DeltaReport | 0 | 只支持手工 `POST /expected-deltas/{id}/report` |
| Review | 0 | 只评 AgentRun，不评场景运行或报告 |
| Failure | 1765 | 1571（89%）未分类，分析信噪比低 |

### 1.3 AR 成功标准

每次新场景执行必须形成唯一 `ScenarioRun`，有序关联所有子 `ReplayRun`；终态后自动形成
`ScenarioReport`（即使无期望，也明确显示 `no_expectation`），报告可被一次性评审。用户从场景
进入运行、报告、证据，不再通过“高级工具”猜入口。

## 2. 业界模式与产品裁决

- Playwright：测试/运行是主对象；Trace、Action、Network、Console、Screenshot 在单次运行下钻。
- Testkube：Workflow Catalog → Execution → Artifacts / Analytics。
- Allure：执行自动生成报告；History、Categories、Attachments 属于报告上下文。
- GitHub Checks：Check Suite → Check Run → Annotation，诊断与对应执行绑定。

裁决：普通用户导航只放工作对象；学习图、审计、Replay Plan、LLM 日志、字段规则是上下文内
诊断能力或开发者工具，不与场景/运行竞争顶级入口。

参考：
- https://playwright.dev/docs/test-ui-mode
- https://playwright.dev/docs/trace-viewer-intro
- https://testkube.io/
- https://docs.testkube.io/articles/triggering-tests
- https://allurereport.org/docs/

## 3. 范围与非目标

### 3.1 本期范围

1. Chain 收敛为 Scenario；TestSuite/Canvas 的业务编排入口收口。
2. 新增场景级运行聚合及子 ReplayRun 归属。
3. 场景期望绑定、运行终态自动报告、报告评审。
4. 普通用户信息架构收敛；诊断资产按上下文下钻。
5. 历史数据确定性回填与失败分类回算。
6. server / extension / web 同步切换，不保留长期双轨。

### 3.2 明确非目标

- 不在 AR 内实现 AP 常驻录制、任务切分、待发现收件箱；无真实数据前不显示“待确认”。
- 不改写采集、对齐、Skill 归纳、回放定位与组件画像引擎。
- 不引入任务队列、消息中间件、图数据库或新前端依赖。
- 不把 Canvas 扩展为通用工作流产品；只迁移可证明的历史关系。
- 不按时间邻近、同系统或名称相似度猜历史 ScenarioRun。
- 不自动把 9 个 ExpectedDelta 绑定到场景；期望关系必须人工确认。

## 4. 目标领域模型

### 4.1 Scenario（由 Chain 一次性改名）

表：`chain` → `scenario`，保留原 ID。

| 字段 | 类型 | 说明 |
|---|---|---|
| id/name/system/steps/created_at | 原字段 | steps 仍用 JSON，避免本期过度正规化 |
| status | active / archived | 禁用用归档，不物理删除有历史运行的场景 |
| definition_version | int | 每次定义修改 +1，初始为 1 |
| updated_at | datetime | 并发编辑检查 |
| origin | learned / manual / legacy_suite | 来源可解释 |

`steps[].chain_id` 同批改为 `steps[].scenario_id`；Skill 引用仍为 `skill_id`。子场景展开规则、
setup/enabled/cleanup/row_anchor_from/overrides 语义保持不变。

**版本规则**：`PATCH /scenarios/{id}` 必须携带 `If-Match: <definition_version>`；不一致返回
409。运行必须保存 `definition_snapshot`，历史运行不随场景编辑漂移。

### 4.2 ScenarioRun

新表 `scenario_run`：

| 字段 | 说明 |
|---|---|
| id / scenario_id | 聚合运行与场景 |
| definition_version / definition_snapshot | 根场景版本 + **递归展开后的闭包快照** |
| expectation_snapshot | 本次运行定格的绑定、ExpectedDelta 内容/版本与映射键 |
| trigger | web / extension / api / suite_migration / canvas_migration |
| executor | server / extension |
| mode | shadow / execute；历史回填可为 legacy_unknown |
| status | queued / running / pass / fail / error / shadow / aborted |
| source_track | demo / real_traffic / ambient / mixed / legacy_unknown；服务端从场景证据来源推导 |
| confirm_side_effect | 新运行必须 bool；历史不可证明时允许 NULL |
| idempotency_key / request_fingerprint | 创建幂等；同键异请求 409 |
| requested_by_user_id | Web/API 用户；插件可为空并记录通道身份 |
| pass/fail/error/shadow/blocked/total_count | 列化汇总，列表禁加载证据 JSON |
| failure_summary | 轻量摘要；全量证据仍在子 ReplayRun |
| started_at / finished_at / created_at | C3 生命周期 |

状态机：

```text
queued → running → pass | fail | error | shadow | aborted
```

终态不可改；相同终态重复提交幂等，冲突终态返回 409。C1 未确认且场景含写操作时，直接形成
`shadow` 终态，**不得启动浏览器**。

`scenario_run.idempotency_key` 建全局 UNIQUE（单租户系统，无需租户作用域，长度 16-128）；
`request_fingerprint = sha256(canonical_json({scenario_id, requested_definition_version, executor,
confirm_side_effect, trigger, requester_identity}))`。同键同 fingerprint 返回原行，同键异 fingerprint 409；
唯一约束兜底并发竞争，不能只用进程锁。

`source_track` 不接受客户端输入。服务端从闭包内各 Skill 的录制会话/evidence 来源确定性推导：全同则
取 demo/real_traffic/ambient，来源不同为 mixed，存量证据不足为 legacy_unknown。只有内部迁移服务可
写 legacy_unknown；Web、extension、普通 API 均无权声明 real_traffic。

运行创建时必须递归展开根场景及子场景，并保存不可变闭包：

```json
{
  "root": {"scenario_id": 17, "definition_version": 3},
  "steps": [
    {
      "execution_index": 0,
      "source_path": [{"scenario_id": 17, "version": 3, "local_index": 0}],
      "skill_id": 315,
      "step": {"overrides": {}, "setup": false, "enabled": true}
    }
  ]
}
```

`execution_index` 是本次运行的唯一有序步号；`source_path` 保留每层场景、版本和局部索引。
根版本不因子场景修改自动变化，因此**不得只保存根 definition_version**。循环引用/深度超限在创建
ScenarioRun 前返回 422；运行后所有挂靠、期望映射与证据展示只认该闭包，不重新读取最新 Scenario。

ScenarioExpectation 的 `step_index` 是其所属 Scenario 的局部索引；生成报告时通过快照
`source_path` 确定性映射到本次 `execution_index`。子场景期望由子场景自身绑定继承，禁止将展开序号
持久化回场景定义。

### 4.3 ReplayRun 归属

`replay_run` 新增：

- `scenario_run_id`（nullable：历史无法确定者为空）
- `execution_index`（递归展开后的 0-based 步号）
- `attempt`（默认 1；重试不覆盖原 run）
- `scope_kind`：`scenario | legacy_unscoped`
- `source_track`：`demo | real_traffic | ambient | mixed | legacy_unknown`（从父运行继承，客户端不可写）

约束与索引：

- `UNIQUE(scenario_run_id, execution_index, attempt)`
- `INDEX(scenario_run_id, execution_index)`
- 保留现有 `status, created_at` 索引

blocked 步不创建虚假 ReplayRun；只进入 ScenarioRun 快照与汇总。

### 4.4 期望、报告与评审

#### ScenarioExpectation

新表 `scenario_expectation`：

- `scenario_id`
- `expected_delta_id`
- `step_index`（nullable：场景级；有值则只消费该步证据）
- `active`
- `confirmed_by_user_id / confirmed_at`
- SQLite 使用两个部分唯一索引（不能依赖 NULL 参与 UNIQUE）：
  - 场景级：`UNIQUE(scenario_id, expected_delta_id) WHERE step_index IS NULL`
  - 步骤级：`UNIQUE(scenario_id, expected_delta_id, step_index) WHERE step_index IS NOT NULL`

只有 confirmed ExpectedDelta 且经人工绑定，才能参与报告比较。创建 ScenarioRun 时必须把递归闭包内
所有活动绑定及 ExpectedDelta 的 `{id, requirement_id, version, changes, scenario_id, local_step_index}`
复制进 `expectation_snapshot`。同一子场景可被多次引用，因此每个快照绑定必须带从根到该场景实例的
`occurrence_path`（各层 local_index 数组）。稳定键算法固定为：

```text
expectation_key = sha256(canonical_json({
  occurrence_path, scenario_id, scenario_definition_version,
  expected_delta_id, expected_version, local_step_index_or_all
}))
```

canonical_json 使用 UTF-8、key 排序、紧凑分隔符；标准库 hashlib 即可，不引依赖。场景级期望只聚合
该 occurrence_path 子树，不能跨同一子场景的另一次引用。报告生成和崩溃重算只读快照，禁止读取
当前绑定或当前 ExpectedDelta，否则运行后改绑会改变历史报告。

#### ScenarioReport

新表 `scenario_report`，与 ScenarioRun 一对一：

- `scenario_run_id UNIQUE`
- `status`: generating / ready / generation_failed
- `coverage_state`: complete / partial / no_expectation
- `source_track`：从 ScenarioRun 定格复制，供列表统计分轨
- `expected/missing/unexpected/drift` 计数
- `attempt_count / last_attempt_at`：生成重试与陈旧任务收割
- `error_code/error_summary`（URL/凭据脱敏）
- `created_at/finished_at`

现有 `delta_report` 改名为 `report_delta`，新增 `scenario_report_id`、`expectation_key`、
`observed_delta_ids` 与 `evidence_replay_run_ids`（后两者为 JSON 列表），继续存每个期望绑定的
四分类结果；增加 `UNIQUE(scenario_report_id, expectation_key)` 防重，不依赖 nullable replay_run_id。
ObservedDelta 增加 `scenario_run_id`，新自动观测使用
`UNIQUE(scenario_run_id, expected_delta_id, replay_run_id)`；历史行允许 scenario_run_id 为空。
列表只读 ScenarioReport 轻量列，明细按需加载。

**无期望不是生成失败**：报告仍为 ready，`coverage_state=no_expectation`，明确标记“结果未被需求
期望覆盖”；不得把所有观测误判为 unexpected。

#### ReportReview

当前 review 表无存量数据；直接改为 `report_review`：

- `report_id UNIQUE`
- `reviewer/user_id`
- `decision`: approved / rejected / changes_requested
- `comment/created_at`

报告与评审均不可变。`changes_requested` 后通过新 ScenarioRun 产生新报告，不覆盖历史决策。
AgentRun 不再进入活动评审队列，只保留开发者审计。

## 5. 运行与报告生命周期

### 5.1 创建与执行

1. 客户端 `POST /scenarios/{id}/runs`，必须带全局唯一 `Idempotency-Key` 和
   `If-Match: <definition_version>`。
2. 服务端先按 idempotency_key 查询：已有且 request_fingerprint 相同则直接返回原运行；同键异请求
   返回 409。无记录时再校验场景版本、C1、角色、Skill/子场景引用，立即落 queued（C3）。
3. 保存递归闭包快照；server executor 内部执行，extension 返回 `execution_url/context`。
4. 每步创建 ReplayRun 前由服务端从 ScenarioRun 定格读取 `confirm_side_effect/source_track/executor`，
   写入 `scenario_run_id/execution_index/attempt`；插件提交冲突值一律 409，不能覆盖 C1/C2。
5. 非 setup 业务步失败后，其余步记 blocked；父状态和计数由服务端根据闭包与子 ReplayRun
   确定性推导，**不信任插件汇总**。同一 execution_index 有重试时，最高 attempt 是有效结果；
   前序 attempt 只用于 flaky/证据呈现，不参与最终计数。
6. 终态事务中先创建 generating ScenarioReport，再提交运行终态。
7. 报告生成成功 → ready；异常 → generation_failed，错误脱敏并可显式重试。

### 5.2 自动观测与报告

将 `app.change.observed` 拆成可复用的“从既有 ReplayRun 提取观测”和“持久化 ObservedDelta”两层。
报告生成不得再次执行浏览器：

1. 读取 ScenarioRun.expectation_snapshot（不读当前绑定）；
2. 按每个 execution_index 的最高 attempt 读取有效 ReplayRun；前序 attempt 仅标 flaky；
3. 对步骤级绑定：由快照 source_path 精确映射一个 execution_index；
4. 对场景级绑定（local_step_index=NULL）：收集该 scenario 在闭包中的全部有效业务步（排除 setup、disabled、blocked），逐 run 提取 ObservedDelta 后按稳定键去重合并 items；**聚合一次再 classify**，不得逐步重复判 missing，也不得任选一个子 run；
5. 调用现有 `classify_delta` 与 `perf_context`；每个 expectation_key 只产生一个 ReportDelta，并记录全部 observed_delta_ids/evidence_replay_run_ids；
6. 聚合 ScenarioReport 计数与 coverage_state；
7. ready 报告进入待评审队列。

生成接口用 DB 唯一约束保证一 run 一 report；并发 finish、重试、插件重复上报不得重复报告。
启动/定时收割器扫描超时 `generating` 报告：有完整子 run 则幂等重算，无完整证据则标
`generation_failed/stale_generation`，不得永久挂起。`retry` 复用同一 ScenarioReport，增加
attempt_count 并 upsert ObservedDelta/ReportDelta，不创建第二份报告。

## 6. API 契约

### 6.1 场景

```http
GET    /api/v1/scenarios?system=&status=&cursor=&limit=
POST   /api/v1/scenarios
GET    /api/v1/scenarios/{id}
PATCH  /api/v1/scenarios/{id}   If-Match: <definition_version>
POST   /api/v1/scenarios/{id}/archive
GET    /api/v1/scenarios/{id}/references
```

AR1 同版本更新 Web、extension、脚本及测试，删除 `/chains` 活动路由；不保留无限期兼容别名。

### 6.2 场景运行

```http
POST /api/v1/scenarios/{id}/runs
Idempotency-Key: <uuid>
If-Match: <definition_version>
{
  "executor": "extension",
  "confirm_side_effect": true
}
```

返回：

```json
{
  "id": 42,
  "status": "queued",
  "mode": "execute",
  "definition_version": 3,
  "execution_url": "/executor.html?scenario=17&scenario_run=42"
}
```

其他端点：

```http
GET  /api/v1/scenario-runs?scenario_id=&status=&cursor=&limit=
GET  /api/v1/scenario-runs/{id}
POST /api/v1/scenario-runs/{id}/finish        # extension 通道；幂等
POST /api/v1/scenario-runs/{id}/abort         # admin/reviewer 或执行通道
```

现有 `/executor/skills/{skill_id}/plan|step|finish` 请求增加
`scenario_run_id/execution_index/attempt` 上下文；服务端校验场景快照中的 Skill 与序号，拒绝任意挂靠。

### 6.3 报告与评审

```http
GET  /api/v1/scenario-runs/{id}/report
GET  /api/v1/reports?status=&coverage=&review_state=&cursor=&limit=
GET  /api/v1/reports/{id}
POST /api/v1/reports/{id}/retry               # 仅 generation_failed
GET  /api/v1/reviews/pending
POST /api/v1/reports/{id}/review
{
  "decision": "approved",
  "comment": "..."
}
```

权限：viewer 只读；reviewer/admin 可执行、确认期望、重试报告和评审；admin 才能归档场景及运行回填。

## 7. Web 信息架构

### 7.1 AR 完成后的默认导航

1. 系统总览
2. 测试场景
3. 运行与问题
4. 报告与评审
5. 系统与环境

“待确认”属于 AP；AR 阶段没有真实候选数据，不展示入口。

用户菜单提供“开发者模式”（默认关闭），开启后显示：步骤库、学习图、审计、Canvas、字段类型、
适配器诊断。删除“高级工具”杂物筐式分组。

### 7.2 页面职责

- **总览**：指标全部改为 Scenario/ScenarioRun 口径；显示待处理失败、待评审报告、无期望覆盖场景。
- **场景列表**：健康状态取最近 ScenarioRun，不再取链首 Skill；支持系统/状态/期望覆盖筛选。
- **场景详情**：概览、步骤、期望、运行历史四区；运行按钮先创建 ScenarioRun。
- **运行列表**：按场景聚合；失败分析成为筛选/统计视图，不再单独顶级页面。
- **运行详情**：摘要 → 步骤/子 ReplayRun → 断言/截图/网络 → 差异报告；学习图/审计通过“上下文”抽屉下钻。
- **报告与评审**：四分类、覆盖状态、期望来源、失败证据、子 run 链接与评审同屏。
- **Canvas**：AR 内降为开发者模式；后续只允许二选一：并入场景编辑器或删除业务入口。

原则：没有后端契约或真实数据的页面不得进默认导航；空态必须说明缺少什么数据以及从哪里产生。

## 8. 历史数据迁移与回填

### 8.1 可确定性迁移

1. 16 Chain 原 ID 改为 Scenario ID；JSON 子链键同步改名。
2. TestSuite 仅在所有 Skill 可确定属于同一 system 时转换：
   - 与现有 Scenario 步骤序列完全一致 → 建映射，不重复创建；
   - 同系统但不一致 → 新建 `origin=legacy_suite` Scenario；
   - 混合系统 → 不自动拆分、不改变语义，保留 legacy suite 审计并要求人工重构。
3. SuiteRun 仅在 suite 已确定映射且 results 内有完整 `run_id` 时创建 ScenarioRun 并关联 ReplayRun；
   写入 `legacy_suite_run_id/legacy_agent_run_id` 来源。历史无法证明的字段使用
   `mode=legacy_unknown`、`source_track=legacy_unknown`、`confirm_side_effect=NULL`，不得伪造 execute/real_traffic。
4. SuiteRun.agent_run_id、suite.canvas_id 作为审计来源，不作为新主链依赖。
5. AR0 的“0 Report/0 Review”不是长期假设：AR1 冻结旧报告/评审写端点；每次迁移前重新计数。
   若发现新增行，原样迁入 `legacy_delta_report/legacy_review` 只读审计表，不丢弃、不强绑新主链。
6. ObservedDelta 保留原 replay_run 证据关系。

### 8.2 禁止猜测

- 普通 Chain 服务端执行过去没有聚合行，禁止按时间邻近把 ReplayRun 拼成场景运行。
- 3115 ReplayRun 无可证明上下文者设 `scope_kind=legacy_unscoped`，仍可从 Skill/审计查看。
- 独立 Canvas 仅当 DAG 和 node_outputs 能恢复完整有序 run_id 时迁移；否则保留开发者审计。
- 9 个 ExpectedDelta 不按名称/系统自动绑场景；由 reviewer 在场景“期望”区确认。
- 失败分类不得猜 E4；证据不足保留 unclassified，并写 `no_deterministic_evidence` 原因。

### 8.3 失败分类回填

复用 `app/change/failure_class.py::classify_run`，批次读取轻量列和必要 JSON：

- 每批 100 行、独立事务、可断点重入；
- 记录 processed/changed/unchanged/unclassified_reason 计数；
- 生成 `artifacts/migrations/ar-backfill-summary.json`（不含敏感 URL/值）；
- 先在 3.9GB 主库副本 dry-run，禁止直接试错生产库。

### 8.4 迁移与回滚纪律

采用 expand → 切流 → contract：AR1-AR5 只增加/改名并保留可审计来源，不删除承载新数据的列。
Alembic downgrade 只用于空测试库和迁移副本验证；一旦 AR2 已产生 ScenarioRun，生产回滚方式是
**回滚代码、保留新表新列**，禁止 downgrade 删除新数据。AR6 destructive contract 前必须：

1. 再次统计旧表写入并冻结旧写端点；
2. 完成只读归档和导出校验；
3. 创建主库文件级备份并记录校验和；
4. 获得用户放行；
5. contract 后若回退，使用备份恢复，不假装 Alembic 能无损重建已删数据。

## 9. 分批实施计划

### AR0：契约与基线锁定（文档批）

- 文件：本文、主计划、HANDOVER、`docs/arch/` 新契约（实现时补）。
- 锁定 16 Scenario、3115 ReplayRun、9/17 Delta、0 Report、0 Review 基线快照。
- 出口：用户批准本方案；不得在批准前改模型。

### AR1：Scenario 身份一次性收敛

- 代码：`models.py`、`api/chains.py→scenarios.py`、`main.py`、`web/src/api.ts`、
  `router.ts`、`ScenarioList.vue`、`ScenarioDetail.vue`、extension 空间面板/执行页、相关 scripts。
- 迁移：rename chain→scenario；补 status/version/origin/updated_at；迁 TestSuite 定义；
  冻结旧 `POST /expected-deltas/{id}/report` 与 `POST /reviews` 写入（只读保留到 AR4）。
- RED：
  - `test_scenarios_api.py::test_chain_ids_survive_table_rename`
  - `test_scenarios_api.py::test_patch_requires_matching_version`
  - `test_ar_migration.py::test_suite_definition_deduplicates_exact_sequence`
  - Web `ScenarioList.spec.ts` / `ScenarioDetail.spec.ts`
- 真机：16 场景 ID/步骤/参数不变；Web 编辑后插件立即读到新版本；旧 `/chains` 不再被任何仓库调用方引用。
- 回滚：仅在 AR2 尚未产生新数据时允许 Alembic downgrade 恢复表名/JSON 键；之后按 §8.4 只回滚代码。

### AR2：服务端 ScenarioRun 主干

- 代码：新增 `app/scenario/service.py`、`api/scenario_runs.py`；改
  `replay/chain_runner.py`、`replay/runner.py`、`models.py`。
- RED：
  - `test_scenario_runs.py::test_start_is_idempotent`
  - `test_scenario_runs.py::test_same_key_different_body_conflicts`
  - `test_scenario_runs.py::test_children_are_ordered_and_snapshotted`
  - `test_scenario_runs.py::test_nested_snapshot_keeps_source_path_and_child_version`
  - `test_scenario_runs.py::test_repeated_subscenario_has_distinct_occurrence_and_expectation_keys`
  - `test_scenario_runs.py::test_expectations_are_snapshotted_with_run`
  - `test_scenario_runs.py::test_idempotency_unique_survives_concurrent_requests`
  - `test_scenario_runs.py::test_source_track_is_server_derived`
  - `test_scenario_runs.py::test_terminal_state_is_immutable`
  - `test_scenario_runs.py::test_c1_shadow_does_not_launch_browser`
  - `test_scenario_runs.py::test_blocked_step_creates_no_fake_replay_run`
- 真机：选一条只读场景与一条写场景，server executor 各跑 execute/shadow；库级核对父子 run、计数与快照。

### AR3：插件执行上下文贯通

- 代码：`extension/src/executor-page.ts`、`background/executor.ts`、`shared/chain-rules.ts`；
  server `api/executor.py`。
- RED：扩展新增 `shared/scenario-run.test.ts`；server：
  - `test_executor_protocol.py::test_step_must_belong_to_scenario_snapshot`
  - `test_executor_protocol.py::test_child_cannot_override_parent_confirm_or_source`
  - `test_executor_protocol.py::test_finish_scenario_run_is_idempotent`
  - `test_scenario_runs.py::test_extension_abort_converges_parent`
  - `test_scenario_runs.py::test_highest_attempt_is_effective_result`
- 真机必须走 `executor.html?scenario=&scenario_run=`：一条 pass、一条 fail、一条用户停止；核对子 ReplayRun、父终态、C3 失败证据。
- 插件与 server 同版本发布；MV3 必须重启 9222 常驻浏览器。

### AR4：自动报告与报告评审

- 代码：新增 `app/reports/service.py`；重构 `change/observed.py`、`api/reports.py`、
  `api/reviews.py`、`change.py`；新增迁移。
- RED：
  - `test_auto_report.py::test_terminal_run_creates_exactly_one_report`
  - `test_auto_report.py::test_no_expectation_is_ready_not_failed`
  - `test_auto_report.py::test_report_uses_existing_run_without_replay`
  - `test_auto_report.py::test_report_uses_expectation_snapshot_after_binding_changes`
  - `test_auto_report.py::test_scenario_level_expectation_aggregates_steps_once`
  - `test_auto_report.py::test_generation_failure_is_auditable_and_retryable`
  - `test_auto_report.py::test_stale_generating_is_collected_without_duplicate_delta`
  - `test_auto_report.py::test_retry_upserts_same_report`
  - `test_reviews.py::test_review_targets_report_and_is_immutable`
  - `test_reviews.py::test_pending_contains_ready_unreviewed_only`
- 真机：绑定一条 confirmed 期望；制造 pass、missing、drift 三种证据；运行后自动出报告并完成评审。再跑无期望场景验证 `no_expectation`。

### AR5：Web 主路径与诊断下钻

- 代码：`GraphWorkspace.vue`、`router.ts`、`GraphOverview.vue`、`ScenarioDetail.vue`、
  新 `ScenarioRunsView.vue/ScenarioRunDetail.vue/ReportReviewView.vue`；复用/收敛
  `ReplayRunView.vue`、`DeltaReport.vue`、`FailuresView.vue`、`ReviewPortal.vue`。
- RED：
  - `GraphWorkspace.spec.ts::default_nav_has_no_advanced_tools_bucket`
  - `ScenarioDetail.spec.ts::uses_scenario_run_status_not_first_skill`
  - `ScenarioRunView.spec.ts::renders_child_evidence_and_report`
  - `ReportReview.spec.ts::reviews_report_in_context`
  - `GraphOverview.spec.ts::metrics_use_scenario_run_denominator`
- 浏览器 1440×900：总览→场景→运行→报告→评审完整走通；默认导航无学习图/审计/Canvas；开发者模式可恢复诊断入口；console 零错误、截图入库。

### AR6：确定性回填与旧主链删除

- 代码：Alembic 幂等回填、`scripts/ar_backfill_audit.py`；删 TestSuite/SuiteRun 活动路由、旧 AgentRun 评审、旧 Chains 命名与重复 UI。
- RED：
  - `test_ar_backfill.py::test_only_provable_runs_are_linked`
  - `test_ar_backfill.py::test_unprovable_runs_stay_legacy_unscoped`
  - `test_ar_backfill.py::test_failure_backfill_never_guesses_expected_failure`
  - `test_ar_backfill.py::test_rerun_is_idempotent`
- 主库副本：upgrade → 数量/外键/抽样校验 → downgrade → upgrade；输出回填报告。生产库按 §8.4 备份与 contract 放行，不用 downgrade 删除新数据。
- 删除闸门：仓库内 `/chains`、Suite 独立执行、AgentRun 活动评审引用为 0；历史审计仍可读。

## 10. 性能、安全与宪法约束

- **性能**：列表只选轻量列并游标分页；不得加载 ReplayRun.plan；报告/证据按需加载；新排序/外键列先建索引。
- **3.9GB SQLite**：新增 nullable 列与小表优先；大 JSON 禁重写；回填小批事务；迁移必须先跑副本。
- **C1**：确认定格在 ScenarioRun；shadow 不启浏览器，子步骤不得绕过。
- **C2**：source_track 由服务端从证据来源推导并贯穿 ScenarioRun、ReplayRun、Report；客户端不可声明 real_traffic；ambient 不混 real_traffic 统计。
- **C3**：queued 起落库；子 run、终态、报告失败、重试、评审和回填决策均可审计。
- **权限**：沿用 Bearer 与角色矩阵；所有写端点纳入 WRITE_GUARD/角色测试。
- **脱敏**：报告错误、回填摘要、截图/网络/LLM 日志继续走现有纵深脱敏；禁止真实 key、网关域名和凭据入库/日志/提交。
- **幂等**：API Header + request fingerprint + DB unique 三层；不得依赖进程内锁。
- **空壳红线**：后端数据契约、生成入口、至少一条真实数据未达成前，不增加默认导航入口。

## 11. Definition of Done

1. 新场景执行 100% 有 ScenarioRun；每个已执行步骤均有且仅有对应 ReplayRun 归属。
2. 新终态运行 100% 产生 ready 或明确 generation_failed 的 ScenarioReport。
3. 无期望场景显式 `no_expectation`，不伪装“无异常”。
4. ready 报告可评审且不可重复；评审可追溯到场景、运行、步骤与证据。
5. 每个失败有 failure_class，或有明确 `no_deterministic_evidence` 原因。
6. 历史 3115 ReplayRun 全部被“确定归属”或 `legacy_unscoped` 记账，零猜测关联。
7. 默认导航无高级工具杂物筐、无空壳页；诊断工具只在上下文/开发者模式出现。
8. Chain/TestSuite/AgentRun Review 无活动双轨；仓库调用引用清零。
9. server/web/extension 三套测试全绿；迁移副本 upgrade/downgrade/upgrade 全绿。
10. 插件真实路径完成 pass/fail/abort/shadow/报告/评审矩阵，截图与用户测试报告入库。

## 12. 阶段闸门与提交纪律

每批独立提交，顺序 AR1→AR6，不跨批混改。每批：

1. 先写失败测试，再实现；
2. 跑定向测试；
3. 跑 server `uv run pytest -q`；
4. 跑 web Node 24 `npm test`；
5. 涉插件批跑 `npm run build && npm test`，并重启 9222 真机；
6. 代码审查：耦合、安全、全调用方、敏感串、`git grep 192.168`；
7. 浏览器用户路径实测，截图入 `demo/sprintAR*/screenshots/`；
8. 用户测试报告、架构契约、README/HANDOVER 同步；
9. 用户放行后进入下一批。

任何批次若只能增加页面而不能建立真实数据生成路径，立即停止，不得以空态页面视为完成。
