# Sprint 32 用户测试报告：链路时间线 + LLM IO 全留存

> 2026-09-28。测试人：代理（用户授权自主闭环）。
> 环境：server 8710（REPLAY_CDP_URL=9222 常驻浏览器链路）、Playwright chromium 1400×960。

## 测试范围

用户诉求：流程图之外，每一次运行、每一步的链路/日志/输入输出/思考都要留存并可
通过链路图查看；链路过程中的 LLM 调用输入输出也要可查。

## 用户路径实测（scripts/s32_screenshots.py，全过）

| # | 步骤 | 结果 | 截图 |
|---|---|---|---|
| 1 | 进入 /timeline，时间轴渲染 | 100 项（8 类型混排，倒序） | 01-timeline.png |
| 2 | 点"LLM"过滤 chip | 只剩 11 项 llm，计数正确 | 02-filter-llm.png |
| 3 | 点 LLM 项展开 | 完整 prompt/response + tokens/耗时 | 03-llm-io.png |
| 4 | 点 Skill 项"下钻查看" | 跳转 /skills/33 详情页 | 04-skill-drilldown.png |

## 易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P3 | 时间轴默认 100 项较长，无分页 | limit 上限 200 可接受；后续可加"加载更多" |
| P3 | replay/report/review 项展开无下钻链接（无对应详情路由） | 已记录；replay 详情页属后续需求 |
| — | LLM IO 展开按需拉取+缓存，二次展开零请求 | 符合预期 |

## 三套测试基线

- server：`uv run pytest -q` → **362 passed**（+4 timeline/llm-detail 用例）
- web：`npm test` → **56 passed**（+4 TimelineView 用例，App.spec 导航断言更新）
- extension：`npm run build && npm test` → **31 passed**（本块未改插件，回归确认）

## 结论

S32 验收通过：链路可视化统一入口落地，LLM IO 全留存可查（单条按需取用，
不经列表全量外泄，与 M3 摘要原则兼容）。
