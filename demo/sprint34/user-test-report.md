# Sprint 34 用户测试报告：竞品差距补齐 + Odoo 多目标验证

> 2026-09-29。测试人：代理（用户授权自主闭环）。
> 环境：server 8710（REPLAY_CDP_URL=9222）、Odoo 17 Docker（8069）、Playwright chromium 1400×960。

## 块 1：竞品差距补齐（run 详情页 + 截图放大）

对标 Katalon/mabl/Testim/Applitools/QA Wolf 盘点：自愈/视觉基线/版本演化/
换参回放/flaky/性能基线/导出/Webhook/需求关联/夜间调度/评审门户均已对齐；
本轮补齐 ①run 级详情下钻页 ②截图点击放大。

| # | 用户路径 | 结果 | 截图 |
|---|---|---|---|
| 1 | /replay-runs/178 直达详情页 | 状态/flaky/耗时/步骤表/断言/归因全渲染 | 01-run-detail.png |
| 2 | 步骤截图墙 | 3 张全部加载（naturalWidth>0） | 02-shot-wall.png |
| 3 | 点击缩略图 → lightbox 开/关 | 开关正常 | 03-lightbox.png |
| 4 | 时间线 replay 项"下钻 run 详情" | 跳转成功 | 04-timeline-drilldown.png |

## 块 2：Odoo（本地 Docker 开源 ERP）多目标全链路

| # | 步骤 | 结果 |
|---|---|---|
| 1 | Docker 部署 Odoo 17 + Contacts 模块 | 8069 就绪，库 skilllens-demo |
| 2 | 常驻浏览器插件录制 Create 流程 ×2（换数据） | 事件 15+15，含图标按钮 aria-label |
| 3 | process → align → induce → assertions | skill #38 PartnerQuickCreateFlow learned |
| 4 | **换参回放**（新动态值 Odoo Replay Dynamic C1） | **run 179 pass**：3 步全过 + 4 断言 + 4 步骤截图 |
| 5 | Odoo DB 副作用核验 | res_partner id=12 由回放真实创建 |
| 6 | run 179 详情页浏览器实测 | 4 张 Odoo 截图墙 + lightbox + 下钻全过（05-odoo-home.png） |

### 多目标暴露的三个缺口（已修，TDD）

1. **图标按钮**：点击命中内部 `<i>`（label 空→噪声过滤丢动作）→ describeElement 上溯可操作祖先取 aria-label
2. **API 集噪声**：偶发请求（autocomplete/轮询）致 LCS 精确匹配丢整步 → 锚点对齐 + API 交集
3. **input 步前置**：Odoo 表单在锚点后才出现 → 按事件时序交错插入

## 易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P2 | Odoo 纯查询流程（Search）0 语义动作，无法学习 | 记录为后续需求（查询类窗口语义） |
| P3 | Update 流程锚点学偏（chatter 头像） | 录制操作规范性问题，脚本已可复用改进 |
| — | Odoo 录制须 >2s 动作间隔（IDLE_MS 语义） | 脚本已按真实用户节奏 |

## 三套测试基线

- server：`uv run pytest -q` → **371 passed**（+4：对齐 2 + 计划 2）
- web：`npm test` → **59 passed**（+2 ReplayRunView）
- extension：`npm test` → **35 passed**（+4 describeElement 上溯）

## 结论

S34 验收通过：竞品高价值差距补齐（run 详情页/截图放大）；**多目标泛化实证**——
在第二个真实 ERP（Odoo）上完成录制→学习→换参回放→副作用落库全闭环，
并修复三个 njmind 上未暴露的泛化缺陷。
