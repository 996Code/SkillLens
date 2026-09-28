# Sprint 33 用户测试报告：链路执行步骤截图

> 2026-09-28。测试人：代理（用户授权自主闭环）。
> 环境：server 8710（REPLAY_CDP_URL=9222 常驻浏览器）、Playwright chromium 1400×960。

## 测试范围

用户诉求：链路执行时除日志外，每次点击按钮等关键节点拍浏览器截图，
链路图上能直接看到做的什么页面。

## 真机链路实测（全过）

| # | 步骤 | 结果 |
|---|---|---|
| 1 | skill #5（SaveFormTableConfig）换新动态值 `s33-shot-verify` execute 回放 | run 178：input/click 步骤全 ok；fail 仅视觉基线断言（换参页面变化 7.7%>2%，预期） |
| 2 | 步骤截图落盘 | start.png + step-01.png + step-02.png（各 ~158KB 真实 PNG） |
| 3 | 出图端点 | 200 image/png 159464 字节；`../x.png` 路径穿越 404 |
| 4 | 浏览器 /timeline 展开 run 178 | 3 张截图墙上屏，全部 naturalWidth>0（真实加载） |

截图：screenshots/01-replay-shot-wall.png（截图墙含"起始页/input 请输入/click 保存"三张缩略图）。

## 易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P3 | 截图墙缩略图固定高 140px，长页面只看到顶部 | object-position: top 已取页面首屏；点击放大属后续需求 |
| P3 | 生成流程（synth_flow）执行未接步骤截图 | 无 UI 消费方，记录为后续需求 |
| — | 旧 run（S33 之前）无 step_screenshots | 展开显示"该 run 无步骤截图"提示，不报错 |

## 三套测试基线

- server：`uv run pytest -q` → 全绿（+4 步骤截图用例）
- web：`npm test` → **57 passed**（+1 replay 展开截图墙用例）
- extension：`npm run build && npm test` → **31 passed**（本块未改插件，回归确认）

## 结论

S33 验收通过：链路执行的每一步（含起始页与失败步骤）都有浏览器画面留存，
时间线 replay 项展开即见——"知道做的啥页面"落地。
