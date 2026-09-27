# Sprint 23：块 V 性能基线（性能漂移进四分类）

> 主计划 v1.6 块 V。UiPath 2026-09-26 发布 agentic 性能测试验证了方向；我们的差异点：
> 性能漂移进 drift 分类（四分类容器），且全确定性。MVP 遗留 TODO（observed.py
> duration_ms=0"真实时序 Drift 留给后续"）在本块兑现。
> TDD 先红后绿；完成后走阶段闸门仪式。

## 设计决策

- **采集**：replay_run 加 duration_ms 列（execute_plan 前后 monotonic 差）；
  API 延迟在 execute_plan 内 request/response 事件配对测得，按 api_template
  聚合进 plan["api_latencies"]（沿用快照旁挂 plan 的加法变更先例，零破坏面）。
- **基线**：滚动基线纯函数——该 skill 最近 N 次（`PERF_BASELINE_WINDOW`，默认 10）
  execute 回放耗时/API 延迟的中位数；无表（历史可从 replay_run 重算，避免状态同步）。
- **判定**：current > median × `PERF_DRIFT_RATIO`（默认 1.5）→ drift 项
  {"type": "perf", value: "回放耗时 中位数 Xms → Yms (+Z%)"}；API 延迟同规则逐模板判定。
  历史不足 3 次不判定（防 N=1 噪声）。
- **清理**：classify_delta 的死代码 timing 钩子（baseline_ms/observed_ms 参数，
  无调用方无测试）删除，由 perf 模块在 report 端点接入替代。
- **呈现**：report 响应附 perf 上下文（baseline/current/history）；
  DeltaReport.vue 性能漂移区块（drift 列表自动含 perf 项）+ 最近 N 次耗时趋势。

## 任务

### T1 采集（runner）
- replay_run.duration_ms 列+迁移；_execute_skill 计时；
  execute_plan request/response 配对测 API 延迟 → plan["api_latencies"]。
- observed.py duration_ms 取 run.duration_ms（兑现 TODO）。
- 测试：替身回放 duration_ms > 0；api_latencies 形状。

### T2 基线与判定（纯函数）
- app/change/perf.py：rolling_baseline(values) → {median, n}；
  perf_drift(history, current, ratio) → drift 项 | None（历史 <3 → None）。
- 测试：中位数、阈值边界、历史不足、空历史。

### T3 报告接入
- report 端点：取该 skill 历史 execute runs 的 duration_ms → 基线 → 判定 →
  drift 追加 perf 项；响应加 perf 上下文。classify 死代码清理。
- 测试：慢回放 → perf drift 进报告；历史不足 → 无 perf 项；响应含 perf 字段。

### T4 前端呈现
- DeltaReport.vue：perf 区块（基线/当前/趋势最近 N 次）+ drift 列表 perf 项样式。
- vitest：perf 区块渲染、无 perf 时不渲染。

### T5 收尾
- 三套测试全绿 + 浏览器实测 + 截图入库 demo/sprint23/ + 用户测试报告 + 文档 + 合并。

## 验收标准（对照主计划块 V）

- [ ] V1 回放耗时+API 延迟滚动基线（中位数）
- [ ] V2 超带宽 → drift 项进四分类（确定性阈值，env 可调）
- [ ] V3 报告页性能漂移区块+趋势
