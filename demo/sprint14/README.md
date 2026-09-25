# Sprint 14 验收记录：编排画布（块 H，图形化编排主体）

日期：2026-09-25。分支 sprint14-canvas。用户方向"图形化编排"落地。

## 验收结果

| # | 功能点 | 结果 | 证据 |
|---|---|---|---|
| H1 | 节点画布 UI | ✅ | /canvas：5 类型节点面板/SVG 画布（端口连线/拖动/删除）/类型化参数表单；零新依赖（手写 SVG） |
| H2 | DAG→图编译 | ✅ | validate（白名单/无环/连通/出入度/必填参数）→ 动态 StateGraph；canvas_dag 版本化保存（行不可变） |
| H3 | 运行可视化 | ✅ | 运行后节点着色（node-ok×5 实测）+ 产物 JSON 下钻 + 运行历史表；截图 3 张 |
| H4 | 首条流水线 | ✅ | 预置"定向回归流水线"真库运行：run 2/3 finished——impact 6 skill → 6 shadow（零浏览器）→ aggregate → review 摘要 |
| — | 三套测试 | ✅ | server **224**（207→224）/ web **29**（23→29）/ extension 27 |

## C1 审查确认（最高优先项）

- replay_batch 的 confirm_side_effect **编译期从画布行定格**（闭包求值一次）；画布行不可变（无 update 端点，改 confirm=新版本新行）；run 端点无请求体不可临时覆盖；前端默认不勾+C1 旁注。

## 审查与修复

- 修2项：lifespan 播种异常加 warning 日志（区分迁移未跑与真实故障）；validate_dag 补 params 类型检查（畸形 payload 500→422）。
- 已知简化（转后续）：单汇聚执行语义（同 key 并行分支会 error 收敛——validate 放行但运行必败，文档标注 v1 限制）；run_graph/compile_and_run 双骨架漂移面（下 sprint 提取 helper）；跨版本 confirm 不可变测试、canvas error 分支测试。

## 用户层实测（浏览器）

- 加载预置画布（下拉→5 节点渲染）→ UI 点运行 → run 3 真实落库 → 5 节点 node-ok 着色 → 点节点产物 JSON 下钻 → 零页面错误。截图：01-canvas-loaded / 02-canvas-run / 03-canvas-node-output。

## Sprint 回顾（宪法 §12）

- #1 图形化编排（M3 主线、用户方向）✓；#3 卖点未滑向"低代码平台"——画布编排的是**自家夜间流水线**，不是给客户编排业务 ✓；#5 C1 编译期定格 ✓；#7 C3 canvas_dag 版本化+agent_run 全产物 ✓。
