# Sprint 9 验收记录：工作台 v0（M1-块C）

日期：2026-09-24。分支 sprint9-workbench-v0。
环境：8710 正式 server + Vue3 工作台（同源托管 /web 静态根）+ 真库。

## 验收标准（主计划块 C / 计划 Task 6）

> 不看 DB/curl 完成"看报告→触发回放→看结果"全流程；C1 UI 门控；只读边界。

## 结果

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | card 聚合端点 | ✅ | GET /skills/6/card 200（14 字段，TDD 3 用例） |
| 2 | reports 读取端点 | ✅ | GET /reports/1 200（真库四分类，TDD 2 用例，红测试暴露 SPA 吞 API 404 行为并锁定） |
| 3 | 前端骨架与 SPA 托管 | ✅ | dist 110KB js + 10KB css；深链 fallback、API 优先、静态资源不误吞（8711/8713 冒烟 + 8710 实测 200） |
| 4 | 列表/详情/报告页 | ✅ | 浏览器结构快照逐页验证（用户测试报告 #1-3） |
| 5 | 回放触发 + C1 门控 | ✅ | shadow 默认；execute 复选门控（未勾禁用）；真实回放 run 14 pass 含快照对比（用户测试报告 #4-5） |
| 6 | 只读边界 | ✅ | 无编辑入口；执行类仅 observe（带门控）；后端仅新增 GET |
| 7 | 全量回归 | ✅ | server **138 passed**、web vitest **12 passed**、extension **24 passed** |

## 交付物

- 后端：cards.py（card 端点）+ reports.py（报告读取）+ SPA 静态托管（dist 感知）
- 前端：server/web/（Vue3+TS+Vite，5 路由：/skills、/skills/:id、/reports/:id、/replay/:skillId）+ README
- 用户测试报告：demo/sprint9/user-test-report.md（U4-U6 发现）

## 过程记录

- 8710 旧进程跑旧代码导致首次冒烟 404——重启后生效；dist 静态文件即时生效但路由/挂载需重启（记入 web README）。
- web vitest 发现 overrides 空串语义：后端空串不回退录制值 → 前端提交前剔除空值（"留空=沿用录制值"对齐）。

## Sprint 回顾（宪法 §12）

- #1 主链路（评审载体）落地 ✓；#3 卖点叙事未滑向"测试工具"——工作台呈现的是四分类变更智能 ✓。
- #5 C1 零违规（UI 门控是加严方向）✓；#7 C3：无新管道环节，读取端点全只读 ✓。
- #10 演示轨：工作台即演示界面 ✓。

## M1 放行预审（S7+S8+S9 对照主计划）

| 块 | 验收 | 状态 |
|---|---|---|
| A 管道可靠性 | 4 债清零 + 基线锚 | ✅ demo/sprint7/README.md |
| B UI 证据层 | 快照全链路 + ui_text 断言 + 回放快照 | ✅ demo/sprint8/README.md |
| C 工作台 | 列表/详情/报告/回放 + C1 门控 | ✅ 本记录 + 用户测试报告 |

**M1 三块全齐，提交用户放行评审 → 开 M2（S10 真实流量，闸口 G1：目标系统授权）。**
