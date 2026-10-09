# AK 块：执行引擎异常收敛层（设计）

> 2026-10-09 立项。触发：用户裁定"异常场景处理能力差"（当日实证：131 run/13s
> 重试风暴、ERPNext 登录假成功、面板 TDZ 挂一半、30s 无界等待）。
> 依据：zcode browserView 一手源码精读（三码分类/预算竞速/瞬态退避）+
> Playwright retries 官方语义 + Polly/resilience4j 熔断标准模型。
> 本文档是 v2.7 主计划修订的 AK 块设计基线。

## 一、问题（现状盘点）

服务端 replay/chain/executor 三模块 **61 处 except/catch**，各自为政：

| 故障形态 | 实证 | 根因类型 |
|---|---|---|
| 重试风暴 | 131 run/13s（skill 18，attach 冲突秒败秒建） | 无重试上限/无熔断 |
| 假成功 | ERPNext 登录 URL 判定 True 实为登录页；Dolibarr 登录例程假 True | 错误被吞/判定通道单一 |
| 挂一半 | 面板 TDZ——mount 中断但 DOM 已写 | 异常中断无收敛出口 |
| 无界等待 | input readback 30s；step POST 45s race | 超时无分层预算 |
| 错误不可读 | "执行中…"永卡；attribution 乱码 | 错误分类缺位（用户看不懂） |

## 二、业界共识（一手源码引用）

- **三码分类**（zcode browserCommandExecutor L113-133）：`cancelled`（AbortError
  最优先判——取消≠失败）> `timeout`（TimeoutError 名/消息正则）>
  `execution_error`；能力缺口单列 `capability_unsupported`。**结构化返回，
  永不 throw**。
- **时间预算制**（zcode L14-17/L729-775）：子操作预算 < 父级预算且留余量
  （截图 2s < surface 3s）；每次尝试只消费**剩余**预算——预算耗尽快败，
  天然封顶（治无界等待与重试风暴）。
- **瞬态白名单重试**（zcode 截图 L139-144 正则）：context destroyed/frame
  detached 类可恢复竞态→**重建上下文后重试**（非原样重试）；白名单外不重试。
- **Playwright retries**：只重试失败用例；首败重过=**flaky 单列**（不与
  passed 混淆）；失败即弃 worker 重建（隔离污染）。
- **熔断器**（resilience4j/Polly）：CLOSED（滑窗失败率）→OPEN（快败不发
  真调用）→HALF_OPEN（放行少量探测，成功关闸）。按通道独立实例。

## 三、设计

### 3.1 分层模型：一个出口 + 三种机制

```
runSkill/run_replay/链步 → 统一收敛出口 ExecOutcome
  ├─ 错误分类（四码，纯函数 classify_exc）
  ├─ 预算管理（Budget：总→步→原语三级传递，剩余制）
  ├─ 有界重试（白名单瞬态 ≤2 次，退避 300ms/800ms + jitter）
  └─ 熔断（通道级：extension CDP / server Playwright 各一实例）
```

### 3.2 四码分类（server/app/exec/failures.py，纯函数、双端同词表）

| 码 | 判定 | 处置 |
|---|---|---|
| `cancelled` | AbortError/用户停止/shouldStop | 立即返回，**不算失败** |
| `timeout` | TimeoutError/超时正则 | 走预算耗尽语义，可换通道重试一次 |
| `transient` | 白名单正则（context destroyed/frame detached/Target closed/ECONNREFUSED 瞬时） | 有界重试（重建上下文） |
| `fatal` | 其余（选择器/参数/断言/business） | 不重试，直达用户 |

与 AJ1 的 run 级 `failure_class`（e1_env/e2_infra/e3_drift）正交：四码是
**机制层**（怎么处置），failure_class 是**语义层**（怎么归因），映射表落库。

### 3.3 预算传递（server runner + extension executor.ts 同构）

- run 总预算（默认 120s，env 可调）→ 每步 = 总预算剩余/剩余步数（下限 5s）
  → 原语（locator 等待）钳制 ≤ 步预算的 60%
- **extension CDP 通道**：预算耗尽发 `Runtime.terminateExecution` 强杀页面内
  例程（zcode L749-775 同款）——防 3s 例程外溢成 30s
- **server Playwright 通道**：per-step asyncio.timeout 包裹（协作取消）

### 3.4 有界重试 + 熔断

- 重试：仅 `transient` 码，≤2 次，退避 300/800ms+jitter；重试前**重建**
  （重连 debugger/重开 context），不原样重试
- 熔断：同通道连续 5 次 `fatal`（滑窗 10 次）→ OPEN 60s → HALF_OPEN 放
  1 个探测。OPEN 期间该通道新 run 直接 `e2_infra` 快败（不发浏览器调用）
- 现有防线保留：plan 节流 409（服务端洪泛闸）与本层正交叠加

### 3.5 收敛出口（消灭假成功的机制保证）

所有执行 API 返回 `ExecOutcome{status, code, detail, budget_left}`，
**不再用 bool**；判定类（登录成功/attach 成功）必须**双通道证据**
（URL+DOM 特征）才置成功——单一证据只置 `uncertain`→按 fatal 处置。

### 3.6 用户直达（错误可读）

`code+detail` → 白话映射表（复用 executor-page 现有 replace 表，双端同源）：
- timeout→"步骤超时（剩余预算 Xs 用尽）——页面慢或选择器失效"
- transient→"页面瞬断已自动恢复重试（第 N 次）"
- fatal→"「按钮名」未找到——页面已改版或前置状态缺失"

## 四、落地切片（TDD，每片红→绿→真机）

| # | 切片 | 侧 | 验收 |
|---|---|---|---|
| AK1 | failures.py 四码分类+瞬态白名单（纯函数） | server | 单测穷举 20+ 错误形态 |
| AK2 | 预算传递+CDP terminateExecution 强杀 | extension | 3s 例程挂死场景 5s 内收敛（现 30s） |
| AK3 | server runner 接 ExecOutcome+分步预算 | server | ERPNext 慢页 run 120s 硬封顶 |
| AK4 | 熔断器（通道级）+OPEN 快败 e2_infra | server | 风暴复现：第 6 个 run 起零浏览器调用 |
| AK5 | 白话映射表双端同源+面板/执行页呈现 | 双端 | 每类错误中文明示（用户可读懂） |
| AK6 | 61 处散落 except 分批收敛到出口（重构批） | 双端 | 全量回归绿+grep 验证裸 except 清零（豁免清单除外） |

## 五、不做（边界）

- 不做跨进程分布式熔断（单机单 worker，进程内状态足够）
- 不做自动换通道（CDP↔Playwright 故障切换）——留 AL 块候选
- 不改 AJ1 failure_class 语义（正交关系，只加映射）
- 存量 61 处 catch 不一刀切——AK6 分批迁移，行为等价回归护航
