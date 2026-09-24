# Sprint 9 用户层闭环测试报告（工作台 v0：界面设计 + 功能易用性/可用性）

日期：2026-09-24。测试人：Agent（browser-use 结构快照 + JS 交互驱动 + 真实 API 回放）。
环境：8710 正式 server（S9 代码）+ 真库（5 skill / 4 delta / 14 report）+ 常驻浏览器回放通道。

## 页面逐项测试

| # | 页面 | 界面设计 | 功能可用性 | 证据 |
|---|---|---|---|---|
| 1 | `/skills` 列表 | ✅ 卡片网格：name/status 徽标/置信度%/证据/断言数/回放状态点（pass 绿·execute）信息密度合理 | ✅ 5 张真实卡片渲染，链接可达 | 结构快照 20+ 元素全上屏；截图 `screenshots/01-skills-list.png` |
| 2 | `/skills/6` 详情 | ✅ 分区清晰（概要/骨架流/变量/断言表/窗口参数/最近回放） | ✅ 断言 4 条 payload 摘要可读（`tpl→200`、`code=200`）；窗口参数表；变量值 chip | 快照含 60 元素；截图 `screenshots/02-skill-detail.png` |
| 3 | `/reports/1` 报告 | ✅ 四栏分色分计数（expected 3/missing 1/unexpected 5/drift 0）+ 需求上下文 + 生成时间 | ✅ 真库数据完整渲染；drift 空态"（空）" | 快照含 54 元素；截图 `screenshots/03-delta-report.png` |
| 4 | `/replay/6` 回放触发 | ✅ 变量覆盖输入 + 模式单选 + delta 输入，说明文案到位 | ✅ **C1 门控交互实测**：选 execute → 复选框出现（"我已确认此操作有副作用，并在旁观察执行过程"）→ 不勾选提交禁用 | JS 驱动 DOM 三态验证；截图 `screenshots/04-replay-launch.png`（shadow 态）与 `screenshots/05-replay-execute-gate.png`（execute 门控态） |
| 5 | 真实回放（页面同款 API） | — | ✅ execute observe：run 14 **pass**，before=`userflow-实测-2026` → after=`s9-workbench-e2e`（覆盖生效），4 断言全过，8 观测项 | API 实测（常驻窗口执行） |

## 易用性发现

| # | 严重度 | 问题 | 处置 |
|---|---|---|---|
| U4 | 低 | 详情页"置信度 100%（1）"括号内数字语义不明（实为版本号 version=1） | 下 Sprint 修文案（去掉括号或标注"版本"） |
| U5 | 低 | Reports 导航硬链 `/reports/1`，无报告列表页——用户需知道 report id | S10+ 报告列表（delta 列表页 + 最近报告） |
| U6 | 低 | execute 模式下 409 语义说明文案已在页内，但 shadow 409 的返回展示区未实测（依赖 delta 确认态） | 已由 vitest 409 用例锁定，真机复测列入下次 |

## 结论

S9 交付面（列表/详情/报告/回放触发）界面与功能均达可用标准；**C1 影子门控的 UI 化呈现完整且交互正确**。U4-U6 均为低severity 文案/入口问题，已记录。测试通过。
