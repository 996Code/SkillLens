# S33：链路执行步骤截图（每次点击/输入留画面）

> 2026-09-28。需求：链路执行时除日志外，关键节点（每次点击/输入）拍浏览器截图，
> 链路图上直接看到"这一步在什么页面"。
> 宪法依据：C3 全链路落库——截图是步骤级执行证据，失败画面是归因关键输入。

## 数据流

```
execute_plan(shot_dir)          每步（成功/失败）拍 step-NN.png，executed 条目带 screenshot 文件名
_attempt                        goto 后拍 start.png；shot_dir = artifacts/steps-{skill}-{ts}/
_execute_skill                  plan.step_screenshots = {dir, files} 旁挂（零 schema 变更）
GET /replay-runs/{id}/step-screenshot?file=   白名单出图（FileResponse image/png）
TimelineView replay 项展开       截图墙（blob URL，caption=起始页/步骤 kind+label+成败）
```

## 关键决策

- **旁挂 plan 而非新表/新列**：与 before_snapshot/api_latencies 同模式，
  plan 消费方只读 url/steps，加法变更零破坏面。
- **fail-open**：替身 page 无 screenshot 能力（测试）/截图异常 → 静默跳过，
  不影响步骤判定与 run 状态（与 S22 视觉基线同语义）。
- **失败步骤也拍**：失败画面（错误弹窗/空白页）是归因 LLM 与人工排查的关键证据。
- **出图白名单双校验**：`file ∈ plan.step_screenshots.files` ∩ 正则
  `^(start|step-\d+)\.png$`——防路径穿越；文件缺失（artifacts 清理）404。
- **flaky 重试**：重试 attempt 自带新 shot_dir，首次失败截图嵌 first_attempt 语义不变。

## 端点

| 端点 | 行为 |
|---|---|
| GET /api/v1/replay-runs/{id} | plan 含 step_screenshots（有截图时） |
| GET /api/v1/replay-runs/{id}/step-screenshot?file= | 200 image/png；404 = run 不存在/文件不在白名单/文件缺失 |

## 前端

- TimelineView replay 项点击 → 拉取 run 详情 + 逐张 blob URL（缓存 Map，
  卸载时 revoke）；caption：start.png→"起始页"，step-NN→"kind label（失败）"。
- 截图墙网格（auto-fill 220px 卡片，img object-fit: cover + top 定位）。

## 测试

- server：`tests/test_step_screenshots.py`（真实 Playwright 落盘 PNG /
  API 白名单出图+404 / fail-open 无能力不挂键）。
- web：`tests/TimelineView.spec.ts` 新增 replay 展开用例（3 张图+caption+
  逐张请求计数）。
- 真机：skill #5 换动态值 execute 回放（run 178）→ start+2 步截图落盘
  （~158KB/张）→ 端点 200 PNG → 浏览器截图墙上屏（scripts/s33_screenshots.py，
  截图入 demo/sprint33/）。

## 已知边界

- 生成流程（synth_flow）执行器未接步骤截图（无 UI 消费方，待后续需求）。
- 换动态数据回放会触发视觉基线断言 FAIL（页面内容变化 >2% 阈值）——
  预期行为，非本块缺陷。
