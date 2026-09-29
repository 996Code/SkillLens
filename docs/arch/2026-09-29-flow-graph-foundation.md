# S38：流程图基座——套件流水线合并 + 执行流程图 + 业务状态 + 目标系统维度

> 2026-09-29。触发：用户三连问——"画布流水线只有一个？测试应分系统？" +
> "套件和流水线能不能合并？流水线才是最直白的流程图" +
> "历史链路等都应以流程图为基座；节点类型太少；要归纳业务状态"。
> 架构定调：**流程图是全系统统一基座**，一切测试产物=节点+边+执行注记。

## 统一图模型（节点类型系统）

| 层 | 类型 | 说明 |
|---|---|---|
| 业务层 | `page` / `action` / `api` | 页面/操作/请求（带截图/IO/成败） |
| | **`state` 业务状态** | 执行时从 API 响应确定性派生 |
| | `assert` 校验 | 断言+结果+跳过原因 |
| 编排层 | `skill_source`（新）/ `replay_batch` / `aggregate` / `review_output` | 套件=线性流水线 |
| 归纳层（后续） | `window` / `semantic` / `align` | 学习管道图化（S39） |

## 交付

### ① 套件↔流水线合并（同一对象两个视图）

- POST /suites → 同步生成线性 canvas_dag（skill_source → replay_batch →
  aggregate），test_suite.canvas_id 指向最新版本（迁移 6463c9f48646）
- 套件执行 = 画布运行（compile_and_run → agent_run 全量节点产物）；
  汇总从 node_outputs 派生；confirm 变化 → 版本化新 canvas（C1 定格语义）
- 新节点类型 `skill_source`（固定技能清单，校验+执行）
- 画布导航改名"编排"（测试流水线统一走"套件"）

### ② 执行流程图（Run 详情图化——流程图基座核心）

- GET /replay-runs/{id}/flow（app/replay/flow_graph.py）：
  page → action×N（截图/成败/策略）→ state×N → assert×N
- 前端 FlowGraph.vue（只读 Vue Flow 组件，全系统共用）：
  节点按执行结果着色（绿/红/灰），点击节点 → 详情面板（截图+IO+错误）
- ReplayRunView 集成：执行流程图区块置于步骤表之前

### ③ 业务状态派生（确定性规则，执行时落库）

derive_states(observed) → plan.business_states：
- 顶层 status/state/code（njmind 等）
- docstatus（Frappe/ERPNext：0 草稿/1 已提交/2 已取消）
- 嵌套 data.status / message.docstatus（网关/Frappe 包装）
真机验证：ERPNext run 197 派生 `docstatus=0 ← frappe.client.save` 状态节点上屏。

### ④ 目标系统维度（分系统）

app/system.py：skill→参考会话首条 navigation host→系统名
（HOST_SYSTEM 映射 + host 兜底）。skills 列表/套件 brief/时间线
（test_run+recording）均带 system 字段。

## 真机验证

- run 197（ERPNext 换参）：流程图 9 节点（page+3action+state+4assert），
  状态节点 docstatus=0 上屏；节点点击→详情面板+截图 ✓
- 套件创建→canvas 同源→画布运行→agent_run 产物→汇总 ✓（测试覆盖）

## 后续（S39，流程图基座续）

- Skill 详情流程图化（骨架+buckets 分支+状态机归纳——多次录制状态序列
  聚合成状态转移图）
- 归纳管道图化（审计 trace → 学习流程图：窗口→语义→对齐→Skill）
- 套件卡片内嵌只读流水线图
