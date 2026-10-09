# Attach 冲突风暴复盘：为什么防线存在还会发生（2026-10-09）

> 触发：用户报告"一直卡在登录页"。复盘对象：同日 11:24（skill 18）与
> 14:19（skill 40）两场 attach 冲突风暴，及防线未生效的完整原因链。
> 本文价值不止于修 bug——它暴露了"防线存在 ≠ 防线生效"的四类系统性缺口，
> 每类都要有对应机制，而非逐个打补丁。

## 一、事实（全部可从 skilllens.db 复核）

| 项 | 数据 |
|---|---|
| 风暴 A | 11:24:42-11:25:08，skill 18，309 条 run，全部 attach 失败 |
| 风暴 B | 14:19:14-14:23:44，skill 40（JeecG 租户用户新增），620 条 run（305 fail+118 running 永卡+2 aborted+其余 fail） |
| 统一错误形态 | `attach 失败：Another debugger is already attached to the tab with id: 1043799610` |
| 风暴 B 起点 | run 2193：`Debugger is not attached to the tab`（detach 后残留操作）→ 之后全链雪崩 |
| 用户所见 | 9222 浏览器：4 个 JeecG login tab + 1 个 executor.html?chain=6&auto=1 挂起 |
| 库内累计 | attach 失败形态 run 共 805 条（风暴 A 309 + 风暴 B 496） |

## 二、防线为什么没拦住（四层原因，层层递进）

### 2.1 进程时间线错位（直接原因，但不是借口）

- 当前 8710 server 进程：**19:06 启动**
- 洪泛节流防线（de0c4d7）：**19:45 提交**
- AK 异常收敛层（f0959f3）：**21:36 提交**

风暴发生在 11:24 和 14:19——**当时的 server 进程不含任何防线**。
但"代码存在"与"防线生效"之间隔着部署与自检，这正是下述缺口。

### 2.2 缺口一：起环境无"代码新鲜度"自检

继任者起环境时 8710/9222 已被旧进程占用（bind 10048 报错才发现），
确认"活着"就继续——没有核验"活着的进程跑的是哪份代码"。
交接环境 ≠ 可信环境。

### 2.3 缺口二：5s 节流闸有 running 前驱盲区

节流逻辑（executor.py executor_plan）：查同 skill 上一条 extension run，
若 `created_at > now-5s` 且 `executor_summary.error` 非空 → 409。

盲区：风暴中后段的前驱是 **5 秒外创建、卡在 running 的 run**——
error 为空 → 放行。"秒败秒建"能拦，"running 挂着 + 新请求进来"拦不住。
118 条僵尸 running 正是这么积累的。

### 2.4 缺口三：僵尸 running 无人收割

`_reap_stale_runs`（10 分钟无步上报→lost）只在 `GET /executor/skills`
被访问时顺带执行。挂起的执行页不调这个端点 → 122 条 running 永卡 5 小时+，
用户面板/工作台持续显示"执行中"——"一直卡在登录页"的直接体感来源。

### 2.5 缺口四：插件侧失败无结构化分类

executor.ts 的 `api()` 30s 超时裸 throw；attach 冲突 catch 后直接
finish(fail)。没有"这类错误该不该重试"的判定——SW 重启后 storage.onChanged
重复消费旧请求（lessons #53）时，每个复活的请求都全新建 run，
无频次/代际校验。

## 三、成熟系统的解法（一手源码，出处标注）

| 机制 | 系统 | SkillLens 对应缺口 |
|---|---|---|
| **每次调用产出结构化失败** `{code, reason, retryable, retryAfterMs, statusCode}`，retryable 是分类的输出而非事后猜 | zcode `apps/zcode-cli/packages/adapters/src/model/failure-classifier.ts` L81-306 | 缺口四 |
| **退避=base×factor^attempt 封顶+jitter×(0.5+rand×0.5)**——抖动防多客户端同步风暴 | zcode `model/runner-retry.ts` L38-56 | （重试策略已入 AK 设计 §3.4） |
| **stale ref 拒绝执行**："ref 已失效，先拿新快照再重试"——旧会话残留操作天然被拒 | zcode `browser/page-command.ts` L55-75 | 缺口二/四 |
| **generation 单调自增**：连接断开→generation+1→持旧 generation 的请求 `backend_unavailable` 快败——"重启后旧请求复活"的根治术 | zcode `browser/index.ts` L72-75, L222-226 | 缺口四（SW 重启同款病） |
| flaky 四态独立分类+worker 失败即弃 | Playwright（harness-study-v2-playwright.md） | （ReplayRun.flaky 已对齐） |
| 滑窗失败率→OPEN 快败 | resilience4j/Polly（breaker.py 已实现） | （AK4 已落地） |

**共识：识别在"每次调用的入口处"，不在事后统计。**

## 四、修复方案（AK6 批次 1，TDD）

1. **节流闸补 running 前驱**：同 skill 存在未收敛 running run → 409
   （两种风暴形态一起堵：秒败秒建 + running 挂着还建新的）。
2. **僵尸收割常态化**：`_reap_stale_runs` 提为 plan 入口必跑
   （复用现有判据，无新概念）。
3. **finish/step 幂等守卫**：SW 重启重复消费旧请求时，对已终态 run 的
   finish/step 上报拒收（stale 写入防二次污染）。
4. **插件侧结构化失败分类**：api 超时/attach 冲突按四码词表分类
   （attach 冲突=fatal 不重试；api timeout=timeout 码），
   AK5 白话映射直达。

## 五、举一反三：病灶清单（超出本 bug 的部分）

"防线存在≠防线生效"的四类缺口是通用模式，逐类自检全库：

| 病灶 | 通用判据 | 本库其他候选 |
|---|---|---|
| 部署时间线错位 | 防线代码提交时间 vs 常驻进程启动时间 | 常驻浏览器 9222 的插件 dist 同样可能过旧（MV3 不热替换） |
| 前驱状态盲区 | 节流/互斥只看"最近一条"而漏未收敛状态 | SW `execRunning` 内存 flag（已补持久锁）；批回放 overrides_map 漏传形态 |
| 收割依赖被动触发 | 清理逻辑挂在低频端点 | VisualBaseline 无效文件清理、llm_call_log 归档是否同样被动 |
| 失败无分类裸 throw | grep `catch (e` 无结构化包装 | executor.ts 70 处 catch（AK6 迁移面）；space-panel 17 处 |

## 六、止损动作（复盘时立即执行）

1. 122 条僵尸 running → lost（同 _reap_stale_runs 判据）。
2. 重启 8710：让节流+AK 防线代码真正加载。
3. 9222 常驻浏览器重启（确保 dist=最新构建）。
4. 挂起的 executor.html?chain=6&auto=1 tab 关闭。
