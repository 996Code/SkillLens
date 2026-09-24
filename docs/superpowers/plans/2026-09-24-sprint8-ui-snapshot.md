# Sprint 8 UI Before/After 快照 Implementation Plan（M1-块B）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 派生自：`docs/specs/2026-09-24-master-delivery-plan.md` 块 B（B1-B4）。

**Goal:** 补齐 UI 状态证据层——插件在锚点前后采轻量状态快照，server 解析进 semantic_action，层 2 断言支持 ui_text 对比，回放执行前后快照入 run——使"字段默认值变化"这类 reqBody 盲区可测。

**Architecture:** ①插件 capture.ts 在锚点动作（click/submit）触发时：动作用 MutationObserver/waitForIdle 采"前快照"（表单 input 值映射/状态标签文本/表格行数），网络空闲后采"后快照"，随窗口上报（kind="snapshot"，payload={phase: before|after, forms: [{name,value}], labels: [{text}], tables: [{rows}]}）；②server process 管道把 snapshot 事件并入窗口产物——写 semantic_action.state_before/state_after（新列，JSON，可空）；③outcome.generate_assertions 从 state_after 与 state_before 的差集生成 ui_text 断言（kind 新增 "ui_text"，payload={label, before, after}）；④runner 在 goto 后与 execute_plan 完成后各采一次同 schema 快照，入 replay_run.plan 旁挂字段 before/after_snapshot；断言评估时 ui_text 用 after 快照对比。

**Tech Stack:** 无新依赖。插件 vitest + jsdom；server pytest。Alembic 迁移加两列。

**Spec:** 宪法 §4.3 层 2(b)（Sprint 5 跳过项）；主计划块 B。

## Global Constraints

- C3：快照事件落 raw_event（kind=snapshot），解析产物落 semantic_action 列；回放快照落 replay_run。
- 快照体积红线：单快照 ≤32KB（表单值截断 1KB/字段，最多 50 字段，超出记 overflow 标记）——防 100KB 教训重演。
- 语义定位复用：快照的 label 与 describe-element.ts 的语义描述同源，不发明新选择器格式。
- 测试基线：S7 合入后为 105+；每任务全量绿。
- 插件消息协议零改动（快照走既有事件通道）。

---

### Task 1: 插件侧快照采集模块（TDD）

**Files:**
- New: `extension/src/content/snapshot.ts`（collectSnapshot(doc): Snapshot）
- New: `extension/src/content/snapshot.test.ts`
- Modify: `extension/src/content/capture.ts`（锚点时序挂接）

**Interfaces:**
- Produces: `Snapshot = { phase: "before"|"after", ts: number, forms: {label: string, value: string}[], labels: {text: string}[], tables: {label: string, rows: number}[], overflow?: boolean }`；capture.ts 在 click/submit 锚点前采 before，上报器空闲回调后采 after（两事件独立 seq）。

- [ ] **Step 1: 红**——snapshot.test.ts（jsdom）：构造含 2 表单/1 表格 DOM → 断言 forms 收集 label+value（label 解析复用 describe-element）；构造 60 字段 → overflow=true 且截到 50。
- [ ] **Step 2: 绿**——实现 collectSnapshot + 单字段 1KB 截断 + 上限 50。
- [ ] **Step 3: capture.ts 挂接**——锚点动作前 enqueue before 快照事件；STOP_RECORDING 终报前采最后一窗口 after（复用现有空闲检测）。vitest 全绿（19+新增）。

### Task 2: server 解析快照进 semantic_action（TDD + 迁移）

**Files:**
- Modify: `server/app/models.py`（SemanticAction 加 state_before/state_after JSON 列）
- New: `server/alembic/versions/*_semantic_state.py`
- Modify: `server/app/ingestion/process.py`（快照事件并入窗口）
- Test: `server/tests/test_process.py`（追加）

**Interfaces:**
- Consumes: kind="snapshot" 的 raw_event（payload 含 phase/forms/labels/tables）。
- Produces: 窗口内 before→state_before、after→state_after；缺失记 null（向后兼容旧数据）。

- [ ] **Step 1: 迁移**——alembic add column（nullable JSON）。
- [ ] **Step 2: 红**——构造含 snapshot 事件的 session → process → semantic-action 接口返回 state_before/forms[0].value 断言；无快照旧 session 回归不受影响。
- [ ] **Step 3: 绿**——process.py 按 phase 归并（窗口内多 after 取最后）。

### Task 3: 层 2 ui_text 断言（TDD）

**Files:**
- Modify: `server/app/learning/outcome.py`（生成）+ `server/app/replay/assert_eval.py`（评估）
- Test: `server/tests/test_outcome.py`、`server/tests/test_assert_eval.py`（追加）

**Interfaces:**
- Produces: generate_assertions 从 state_before≠state_after 的 forms 生成 `{kind:"ui_text", payload:{label, before, after}}`；evaluate_assertions 对 ui_text 用回放 after 快照对比 `after` 值（回放无快照时 skipped）。Skill 卡片断言计数自然含新类。

- [ ] **Step 1: 红**——outcome：有差集的 state 生成 ui_text 断言；assert_eval：构造 observed_snapshot → 相等 PASS/不等 FAIL/缺失 skipped。
- [ ] **Step 2: 绿**——两处实现。
- [ ] **Step 3: 全量**。

### Task 4: 回放前后快照（TDD + 浏览器测试）

**Files:**
- Modify: `server/app/replay/runner.py`（goto 后/execute 后采快照）
- New: `server/app/replay/page_snapshot.py`（extract_forms/labels/tables——与插件 schema 对齐的 DOM 采集，Playwright 版）
- Test: `server/tests/test_runner_browser.py`（追加）

**Interfaces:**
- Produces: replay_run 行 JSON 新键 before_snapshot/after_snapshot（随现有 executed 落库通道）；ui_text 断言评估消费 after_snapshot；水合竞态防护对快照采集不干扰（先确认输入再采）。

- [ ] **Step 1: 红**——mock.local 表单页：跑 execute_plan → run 里有 before/after 快照，after.forms[0].value == 注入值。
- [ ] **Step 2: 绿**——page_snapshot.ts 同款逻辑（getByPlaceholder→input_value 采集；标签文本采集）。
- [ ] **Step 3: 全量**。

### Task 5: 端到端验收 + E2E 修复轮（预留 1-2 轮）

- [ ] **Step 1: 真机链路**——常驻窗口 auto_record（含新快照事件）→ process → semantic-actions 含 state_before/after → induce → assertions 含 ui_text → observe（常驻窗口可见）→ replay_run 含前后快照。
- [ ] **Step 2: 默认值盲区实测**——njmind 表单改一个字段默认值（网页操作），重新录制→归纳→旧 ui_text 断言在 observe 中 FAIL（MVP 测不出的场景，本 Sprint 核心价值证明）。
- [ ] **Step 3: 全量回归**（pytest + vitest）。
- [ ] **Step 4: lessons 记录 + 合并 main（本地 merge + 删分支）**。
