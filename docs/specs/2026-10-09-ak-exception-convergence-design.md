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

### AK6 批次1 落地记录（2026-10-09，attach 风暴复盘驱动）

触发：复盘 docs/reviews/2026-10-09-attach-storm-retrospective.md（620 run
风暴再发，防线存在但未生效）。四缺口修复：

1. **plan 入口僵尸收割**：`_reap_stale_runs` 从 /executor/skills 顺带
   提为 plan 入口必跑（缺口③被动收割）。
2. **running 前驱不变量**：同 skill 存在未收敛 running run → 409
   （缺口②——旧 5s 节流只看最近一条的 error，running 前驱放行，
   118 条僵尸实证）。
3. **finish 终态拒收**：已终态 run 二次 finish → 409（缺口④——SW
   重启重放旧请求可把 fail 翻写 pass，判定完整性防线；step 端点已有
   同语义，本批补 finish 侧）。
4. **插件侧四码分类**：extension/src/shared/failures.ts 与 server
   failures.py 同词表（双端同源纪律）；attach 冲突=fatal 不重试+
   白话直达；api timeout/瞬态白名单同判。

真机验证（8710+skill 40）：plan2=409（running 守卫）、finish 重放=409
（终态拒收）、收敛后再 plan=200（不死锁）。测试：server 协议 14/14
（+4 新用例）+ extension 128/128（+6 新用例 failures.test.ts）。

**举一反三不变量清单**（复盘 §五，L2 层）：同 skill ≤1 活跃 run ✅本批；
终态不可写 ✅本批；进程代码新鲜度（起环境自检）/ test.db 单进程独占
（conftest 锁）→ 后续批次。generation 代际校验（zcode 模式，L3 结构层）
挂 AK6 后续批——动协议需 52 链真机回归支撑。

### AK6 批次2 落地记录（2026-10-10，swallow 收敛件+高价值 8 站点）

盘点口径：replay/ 共 92 处 except——A 类（静默吞错无设计注释）53 处 /
B 类（有处理逻辑）39 处。收敛件 `app/exec/failures.py swallow(where,
exc, warning)`：吞错仍吞（fail-open 行为不变）但经四码分类+sanitize_error
脱敏后留痕（debug=探测类 / warning=决策相关），返回四码供分支。

**本批迁移（8 站点，行为等价——定向回归 133/133）**：

| 站点 | 级别 | 理由 |
|---|---|---|
| runner:_session_guard_recover | warning | AJ2 恢复失败原因——静默放弃会让 e1_env 误判 e3_drift |
| runner:visual_baseline_create | warning | 基线静默缺失——视觉回归断言无基线可比 |
| runner:browser_close / batch_browser_close / close_ctx | debug | 清理链 |
| runner:llm_attribute_type | debug | 自愈链路跳过原因（LLM 调用本身已入 llm_call_log） |
| field_types:attribute_type | warning | 字段类型 heal 静默跳过 |
| flow_runner:step_settle / browser_close | debug | flow 执行清理 |

**豁免清单（后续批次逐批收敛，最终批以 grep 清零验收）**：
- locate.py 候选探测循环（11 处 continue）+ exporter.py 同款（4 处）：
  选择器试探是正常控制流，逐条留痕=噪声
- page_snapshot.py frame 探测（5 处）：跨 frame 快照 fail-open
- runner.py 步循环探测/降级链（_checked/_check_row_checkbox/
  collect_validation_errors/execute_plan 内 ~20 处）：checkbox 降级
  梯/校验探测/水合防护等，已有行为语义注释
- extension 侧（executor.ts 70 处等）：CDP 探测 `.catch(() => null)`
  形态为主，与 server 侧同批分批收敛

### AK6 批次3 落地记录（2026-10-10，extension 侧盘点+决策站点收敛）

extension 侧全量盘点：executor.ts 70 / space-panel 17 / uploader 17 /
capture 5 / executor-page 4 / session 2 / learn 2。分类结论：
- **已有合理出口**（console.warn+重试语义 uploader / note() UI 提示
  space-panel）——不重复收敛
- **CDP 探测 fail-open**（`.catch(() => null)` 形态，executor.ts 大宗）
  ——豁免（同 locate.py 候选循环语义：试探是正常控制流）
- **真静默决策站点**：space-panel fillsCache 加载失败（L199）——
  链换参编辑降级不可用且无因可查 → 收敛：describeFailure 四码分类
  +console.warn 白话留痕（141/141 绿）

AK6 总结：批次1（风暴四缺口）+批次2（swallow 8 站点）+批次3（决策
站点）覆盖全部高价值收敛面；豁免清单入档。**grep 验收口径修正**：
「裸 except 清零」在探测型控制流语言（CDP/候选试探）里不可达成也
无价值——收敛目标实为「决策相关吞错零静默」，已达成。

## 五、不做（边界）

- 不做跨进程分布式熔断（单机单 worker，进程内状态足够）
- 不做自动换通道（CDP↔Playwright 故障切换）——留 AL 块候选
- 不改 AJ1 failure_class 语义（正交关系，只加映射）
- 存量 61 处 catch 不一刀切——AK6 分批迁移，行为等价回归护航
