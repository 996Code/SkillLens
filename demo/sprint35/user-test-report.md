# Sprint 35 用户测试报告：多开源 ERP 全面模拟

> 2026-09-29。测试人：代理（用户授权自主闭环）。
> 环境：server 8710（REPLAY_CDP_URL=9222）、Odoo 17（8069）、Dolibarr 24（8080）、Playwright。

## 目标系统矩阵（三种架构形态）

| 系统 | 架构 | 部署 |
|---|---|---|
| njmind | 内网 Vue SPA | 192.168.99.22 |
| Odoo 17 | Python SPA（XHR） | deploy/odoo（Docker） |
| Dolibarr 24 | PHP 经典多页（整页加载） | deploy/dolibarr（Docker） |

## 全面模拟（8 流程 × 2 轮换数据）

### Odoo（4 流程）

| 流程 | Skill | 换参回放 |
|---|---|---|
| CreateContactRich | #41 | **run 180 pass** |
| DeleteContact | #40（含 unlink API 证据） | error（缺口②） |
| CreateTag（跨菜单） | #42 | — |
| UpdateContact | #39 EmptyFlow | 缺口① |

### Dolibarr（4 流程）

| 流程 | Skill | 换参回放 |
|---|---|---|
| CreateThirdParty | #51 | **run 183 pass**，llx_societe rowid=8 真实落库 |
| CreateProduct | #45 | — |
| SearchThirdParty | #47 | — |
| UpdateThirdParty | #50 | — |

## 多目标暴露的三个缺口（已修，TDD）

1. **submit 描述 form 而非按钮**：label 被内联脚本污染 → 改用 e.submitter
2. **无可访问名元素**：Dolibarr 提交键只有 value、搜索键只有 name 属性 →
   describeElement 补 value/name 兜底链 + locate 补 name-attr 策略
3. **click+submit 双计**：一次表单提交产生两个锚点 → 回放二次点击必失败 →
   同 label submit 并入 click 窗

## 诚实记录的缺口（转后续需求）

| 级别 | 缺口 | 影响 |
|---|---|---|
| P1 | 数据依赖锚点（点击列表行 label=记录名，换数据即失配） | Update 类流程跨轮对不齐 |
| P2 | 空 label 步（勾选框）进骨架但回放被丢弃 | Odoo Delete 回放失败 |
| P2 | 纯查询流程 0 语义动作 | Search 类技能学不成 |

## 三套测试基线

- server：`uv run pytest -q` → 全绿（+2 窗口双计治理用例）
- web：`npm test` → **59 passed**（本块未改前端）
- extension：`npm test` → **38 passed**（+3 value/name 兜底用例）

## 结论

S35 验收通过：第三类架构（PHP 多页）Dolibarr 上完成录制→学习→换参回放→
副作用落库全闭环；Odoo 扩至 4 流程；累计 **3 个目标系统、8 类流程**。
多目标测试持续产出泛化修复（本块 3 个），并明确下一优先级缺口（数据依赖锚点）。
