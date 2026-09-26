# Sprint 19 流程生成 + 多站点实测 Implementation Plan（块 R，S18 T4 并入）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 依据：主计划 v1.5 块 R（用户指令：不仅复刻原流程，要归纳生成新流程）+ 块 P 深化（多站点）。

**Goal:** Evidence-backed Flow Synthesis——系统从学到的证据中**生成从未被演示的新流程**并执行验证、自学习；多站点（网易/搜狐等）实测管道鲁棒性；S18 T4 夜间开发一例收尾。

**Architecture:** ①**R1 流程提案**：`synth_flow(db, goal, system_hint)`——收集该系统的已知证据（skill 骨架签名集+变量名+锚点 label 集）→ LLM（purpose=flow_synthesis）把目标分解为步骤序列 [{kind: goto|input|click, target, value?}]，每步的 target 必须引用已知锚点/变量（goto 的 URL 必须来自已知页面）→ **确定性回查**（每步 target 在证据集合中，子串匹配）→ 落 `synth_flow` 表（goal/steps/status proposed|verified|executed|failed/evidence_refs/execution_log）。②**R2 执行**：复用回放通道（execute_plan 的 locate/fill/click）——CDP 常驻窗口可见；C1：含写方法（POST 模板的 API 关联锚点）需 confirm。③**R3 自学习**：执行成功 → 以执行过程录制（插件在常驻窗口开着录制！生成的流程执行时插件同步采集）→ process → 直接 induce（observed_count=1）→ **candidate skill（conf≈0.45，v3 §27 语义：系统自己发现的新流程）**。④**R4 多站点**：网易新闻（news.163.com 导航流）+ 搜狐（www.sohu.com 搜索流）各 2-3 会话采集学习，验证管道。⑤**S18 T4**：夜间开发一例（请假表单加字段）真跑通。

**Tech Stack:** 1 迁移（synth_flow 表）；LLM 1 次调用/流程（目标分解）；执行复用回放通道。

## Global Constraints

- LLM 边界：只做目标分解与步骤编排；回查/执行/学习全确定性。
- C1：生成流程含写操作锚点 → 执行需 confirm（与回放同门控）。
- C3：synth_flow 全程落库（提案/回查/执行日志）。
- 测试基线：262/28/34；仪式全流程。

---

### Task 1: synth_flow 模型 + 提案/回查（TDD + 迁移）
- 迁移：synth_flow 表（id/goal Text/system_hint String(200)/steps JSON/status/evidence_refs JSON/execution_log JSON nullable/created_at）。
- learning/synthesis.py：`collect_evidence(db, system_hint)`（骨架签名/锚点/变量/页面 URL 按 API 前缀过滤）+ `build_prompt` + `verify_steps`（每步 target∈证据集）+ `synth_flow(db, goal, system_hint)`。
- 端点：POST /api/v1/flows/generate {goal, system_hint}；GET /flows（列表）；GET /{id}。
- 测试：提案落库/回查失败（引用未知锚点）→ status=proposed+notes；证据收集过滤。

### Task 2: 流程执行 + 自学习（TDD）
- POST /flows/{id}/execute {confirm_side_effect=false}：C1 检查（步骤锚点关联写 API→需 confirm）→ 浏览器执行（goto/input/click 循环，复用 locate）→ execution_log 落库 → status=executed|failed。
- 自学习：执行前确保插件录制开着（CDP ext_call START_RECORDING）→ 执行 → STOP → process → induce → candidate skill 关联 synth_flow_id（skill.notes 记"synthesized"）。
- 测试：门控 409/执行日志/失败收敛。

### Task 3: 多站点实测（网易+搜狐）
- 采集：网易新闻导航流 2 会话 + 搜狐搜索流 2 会话（常驻窗口）→ process → align → induce → 断言 → 换参回放。
- 发现问题即修（块 P 模式）。

### Task 4: 流程生成真演示 + S18 T4 + 仪式收尾
- 真演示：新浪上生成"搜索低代码并点击第一条结果标题"（从未整段录制过的组合）→ 执行 → 自学习 candidate。
- S18 T4：dev-plan 全链一例（请假表单加紧急联系电话字段）。
- 全量三套 → 审查 → 文档 → 浏览器实测截图 → 合并。
