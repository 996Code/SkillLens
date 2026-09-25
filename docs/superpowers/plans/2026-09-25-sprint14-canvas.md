# Sprint 14 编排画布 Implementation Plan（块 H，图形化编排主体）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划块 H（用户方向：图形化编排）。前置：S13 agents 运行时（图/批回放/impact 就绪）。

**Goal:** 工作台新增编排画布——节点式流水线可视化编排（拖放节点/连线=数据流），后端把画布 DAG 编译成 LangGraph 执行，运行历史与节点产物可下钻。

**Architecture:** ①**H1 画布 UI**（前端）：`/canvas` 路由——SVG 画布 + 节点面板（节点类型：变更集源/Impact 选择/批回放/聚合/评审输出）+ 拖放添加 + 连线（端口点击连线，v1 不做自由拖线）+ 节点参数表单（每类型固定字段）+ 保存/加载 DAG JSON。**不引重型图库**（vue-flow 等）——手写 SVG + 绝对定位节点（节点数 ≤8，规模可控），避免新依赖与 vite 版本风险。②**H2 编译执行**（后端）：`canvas_dag` 表（id/name/dag JSON/created_at）+ `POST /api/v1/canvas/{id}/run`——DAG 校验（拓扑序/节点类型白名单/必填参数）→ 编译成 LangGraph 图（节点类型映射到 S13 的执行函数：change_source=构造 change_set / impact_select=analyze_impact / replay_batch=run_replay_batch（C1 默认 shadow，confirm 需画布级显式参数）/ aggregate=计数 / review_output=生成 markdown 摘要）→ run_graph 通道执行落 agent_run（graph_name=canvas:{id}）。③**H3 运行可视化**：`GET /api/v1/canvas/{id}/runs`（该画布的 agent_run 列表）+ 前端画布上节点状态着色（运行中/完成/错误）+ 节点产物点开看 JSON。④**H4 首条流水线**：预置"需求→定向回归→晨间摘要"画布（等价 S13 夜间图 + review 节点），真实跑通一次。

**Tech Stack:** 前端零新依赖（手写 SVG 画布）；后端 1 迁移（canvas_dag 表）；复用 S13 runtime。

## Global Constraints

- C1：画布 replay 节点默认 shadow；confirm_side_effect 是画布保存时的显式参数（默认 false），运行时不可临时改。
- C3：canvas_dag 版本化保存（不覆盖，新行）；agent_run 记录 canvas_id。
- 测试基线：207/27/23；仪式全流程；浏览器实测画布交互（截图）。

---

### Task 1: canvas_dag 表 + DAG 校验/编译器（TDD + 迁移）
- 迁移：canvas_dag 表（id/name String(100)/dag JSON/created_at）。
- server/app/agents/canvas.py：`validate_dag(dag) -> (ok, errors)`（节点类型白名单/入度出度/拓扑无环/必填参数）；`compile_dag(db, canvas_id) -> 执行图`（节点类型→S13 函数映射，线性拓扑按拓扑序接线；v1 支持线性链与单汇聚，不做任意分叉并行）。
- 端点：POST /api/v1/canvas（保存，版本化新行）、GET /api/v1/canvas（列表）、GET /api/v1/canvas/{id}。
- 测试：合法 DAG 通过；环/未知类型/缺参拒绝；保存版本化。

### Task 2: 画布运行 + 运行历史（TDD）
- POST /canvas/{id}/run → run_graph(graph_name=f"canvas:{id}")；agent_run.input 带 canvas_id。
- GET /canvas/{id}/runs → 该画布 agent_run 列表（id/status/started_at/node_outputs 摘要）。
- C1：编译时读画布 replay 节点的 confirm 参数（默认 false）。
- 测试：跑预置 DAG → agent_run finished + runs 列表含它；C1 默认 shadow 断言。

### Task 3: 画布前端（vitest）
- /canvas 路由 + CanvasView.vue：左节点面板（5 类型卡片）/中 SVG 画布（节点框+端口+连线）/右参数表单（选中节点的类型化字段）/顶部保存+运行按钮。
- 交互 v1：点面板添加节点（自动布局网格）→ 点节点 A 输出端口再点节点 B → 连线；点节点选中之→参数表单；删除节点/连线。
- 运行态：运行后节点按 node_outputs 状态着色；点节点看产物 JSON 折叠块。
- 加载：/canvas 列表选择加载；预置画布 seed（后端启动时若无画布则插入"定向回归流水线"预置 DAG）。
- vitest：添加节点/连线/参数编辑/保存调用 mock/运行后着色。

### Task 4: H4 首条流水线实测 + 仪式收尾
- 真库：预置画布运行一次（impact→shadow 批→聚合→摘要）→ agent_run finished；浏览器实测画布全交互（截图 4+）；全量三套 → 审查 → 文档 → 报告 → 合并。
