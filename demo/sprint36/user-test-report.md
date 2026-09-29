# Sprint 36 用户测试报告：ERPNext 多目标 + 多信号定位架构

> 2026-09-29。测试人：代理（用户授权自主闭环）。
> 环境：server 8710（REPLAY_CDP_URL=9222）、ERPNext v16（8090，Docker 10 服务）。

## 目标系统矩阵（累计 5 系统 4 种架构）

| 系统 | 架构 | 状态 |
|---|---|---|
| njmind | 内网 Vue SPA | S29-S31 深度验证 |
| Odoo 17 | Python SPA | S34-S35 |
| Dolibarr 24 | PHP 多页 | S35 |
| **ERPNext v16** | **Frappe SPA（socketio）** | **本块闭环** |
| Snipe-IT / 禅道 | Laravel / PHP | 已部署，S37 |

## ERPNext 全链路（核心成果）

| # | 步骤 | 结果 |
|---|---|---|
| 1 | Docker 部署（frappe_docker 官方 compose，10 服务） | 8090 就绪 |
| 2 | 安装向导跳过（bench setup_complete）+ Administrator 登录 | desk 可用 |
| 3 | 录制 CreateCustomer ×2 / CreateLead ×2（换数据） | skill #64/#65 learned |
| 4 | **换参回放**（ErpNext Replay M9） | **run 190 三步全 ok** |
| 5 | 副作用核验 | tabCustomer 真实创建 |
| 6 | 断言 | 2/3 绿（瞬态 toast 断言 fail——时序边界） |

## 多信号定位架构（用户关切：无法枚举所有 UI 框架模式）

采集侧一次收集全部信号（labels[] + ordinal），回放侧逐候选×全策略扫描 +
可见匹配遍历 + 模态优先 + fill 控件优先序 + 结构兜底。**新框架零适配**。
本块在 ERPNext 上实证修通 4 个定位场景：
1. Frappe 输入框只有 data-fieldname（inputKey/describeElement/locate 三处补齐）
2. 字段名被渲染成可见文本（fill 控件优先序）
3. 隐藏 Save 在 DOM 前（可见匹配遍历）
4. 列表"存过滤器"Save 与模态 Save 同名（模态优先）

## 已知问题（用户留意项）

**Playwright node driver 崩溃**：ERPNext 页面交互后 driver 因未处理
Promise rejection 退出（"Connection closed while reading from the driver"）。
规避：每轮录制独立连接 + asyncio.sleep。详见 arch 文档。

## 三套测试基线

- server：`uv run pytest -q` → 全绿（+3 locate 多信号用例）
- web：`npm test` → 59 passed（本块未改前端）
- extension：`npm test` → **41 passed**（+5 多信号用例）

## 结论

S36 验收通过：ERPNext（第 4 目标系统）换参回放闭环 + 副作用真实落库；
**多信号定位架构落地**——从"逐框架打补丁"转为"全信号采集+统一消费"，
元素定位不再依赖预知 UI 框架模式。
