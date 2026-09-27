# Sprint 23 用户测试报告：块 V 性能基线（性能漂移进四分类）

> 日期：2026-09-27 · 分支：s23-perf-baseline · 计划：docs/superpowers/plans/2026-09-27-sprint23-perf-baseline.md
> 目标：兑现 MVP 遗留 TODO（observed duration_ms=0）——回放耗时+API 延迟滚动基线，
> 超阈值漂移进 drift 分类（全确定性）。对标 UiPath 2026-09-26 agentic 性能测试方向，
> 差异点：性能漂移进四分类容器而非独立产品。

## 一、测试覆盖与结果

### 1. 三套测试全绿

| 套件 | 结果 | 说明 |
|---|---|---|
| server pytest | **325 passed**（309+16） | 新增 test_perf.py(9)+test_perf_capture.py(3)+test_perf_report.py(4)；classify 死代码清理零回归 |
| web vitest | **45 passed**（43+2） | DeltaReport perf 区块：渲染（基线/趋势条 4 根）/旧报告 404 隐藏 |
| extension | **31 passed** | 不受影响 |

### 2. 真实环境闭环实测（skill 8 新浪搜索，只读）

| 步骤 | 结果 |
|---|---|
| 3 次 execute 回放 | duration_ms 全部落库（546/516/718ms）✓ |
| 建需求→确认→observe（第 4 次回放） | observed_delta.duration_ms=514（真实耗时，MVP TODO 兑现）✓ |
| 生成报告（#8） | **perf 上下文**：基线中位 546ms、当前 514ms、历史 [546,516,718]；drift 空——**无误报**（0.94x < 1.5x 阈值）✓ |
| 浏览器报告页 | 性能基线区块渲染（中位数/本次/趋势条），**零控制台错误** ✓ |
| 截图 | screenshots/01-report-perf-block.png ✓ |

### 3. 漂移判定的正向验证（单测层）

真实环境 4 次回放耗时稳定未触发漂移（符合预期——新浪搜索页性能稳定）；
漂移路径由单测覆盖：历史 [900,1000,1100] 中位 1000 → 当前 5000（5x）→
perf drift 项进报告；API 延迟 110→600（5.5x）同规则进 drift；
历史不足 3 次不判定（防 N=1 噪声）；恰好 1.5x 不判（严格大于）。

## 二、易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P3 | 趋势条无时间轴标签（只有 hover title） | 可接受——区块小而聚焦；后续可加 |
| P3 | API 延迟漂移项在 drift 列表无专门图标（与 api_status drift 同样式） | 转后续需求 |
| P3 | 历史窗口固定 10 次（PERF_BASELINE_WINDOW 未暴露 env） | 内部常量；需要时再配置化 |

## 三、安全与耦合审查

- 判定全确定性（中位数×阈值），零 LLM ✓
- classify_delta 死代码 timing 钩子（baseline_ms/observed_ms 参数，无调用方无测试）删除——由 perf 模块替代 ✓
- perf_context 共享 helper：report 生成端点与 /reports/{id}/perf 只读派生端点共用，无重复逻辑 ✓
- GET /reports/{id} 保持纯读边界不变（perf 是独立端点）✓
- API 延迟采集在 execute_plan 事件层（request/response 配对），替身无 on("request") 时自然跳过 ✓
- diff 敏感串扫描：无泄露 ✓

## 四、环境教训（本轮踩坑）

web 测试一度全红——根因是 `npm test` 没带 Node 24 PATH 前缀跑在系统 Node 22.10 上
（不支持 require ESM，@exodus/bytes 报错）。**AGENTS.md 的 PATH 前缀铁律再次验证**；
误删 package-lock.json 重装后用 `git checkout -- package-lock.json && npm ci` 恢复。

## 五、验收标准对照（主计划块 V）

- [x] V1 回放耗时+API 延迟滚动基线（中位数，replay_run.duration_ms+plan.api_latencies）
- [x] V2 超带宽 → drift 项进四分类（PERF_DRIFT_RATIO env 可调，历史<3 不判定）
- [x] V3 报告页性能漂移区块+趋势（真实报告 #8 浏览器验证）
