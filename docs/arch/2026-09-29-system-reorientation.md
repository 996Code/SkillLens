# S37：系统重定向——从"回放工具"到"自动测试员"

> 2026-09-29。触发：用户实测控制台后九问（流水线只有一个/Skill 看不懂/
> 时间线乱/回放大量失败/评审审计无价值/仪表盘错位）。审查结论三断层：
> 概念断层（开发者词汇）、架构断层（学习↔套件没打通、事件流≠测试流）、
> 语义断层（断言假阴性）。本 sprint 按根治标准逐块修复。

## 块 1：断言语义根治（pass/fail 说真话）

**根因 A：换参数据 + 视觉基线断言 = 必然 fail（假阴性）**
换参回放是"模拟人工用不同数据操作"，页面内容变化是预期。修复：
`_attempt` 感知 has_overrides（overrides 含非空值）→ 视觉差异降级为
skipped（"换参数据回放：视觉差异为预期，已记录不判定"）。同参数回放
+ 页面变更仍是真实回归信号 → fail（语义拆分，测试同步更新）。

**根因 B：toast 瞬态断言**
toast 一闪而过，after 快照时机必然错过。双通道根治：
- 采集侧：execute_plan 在 settle 窗口内轮询常见 toast 容器
  （.toast/.alert/[role=alert]/.ant-message 等 12 类），捕获文本经
  `observed_toasts` 传给断言评估
- 评估侧：observed_toasts（主）+ 快照 toasts（补充）双通道；两通道
  都未观察到 → skipped（瞬态性本质，不产生假阴性）

**真机验证**：ERPNext skill #64 从 5 连 fail → run 191 **pass**；
Dolibarr skill #51 换参回放 run 192 **pass**。

## 块 2：时间线重构为测试活动视角

GET /api/v1/timeline 重构：默认主行只有两类**测试活动**——
- test_run：自动测试运行（操作流程名/状态/模式/步数/耗时）
- recording：录制学习会话（事件数 + 学到的操作流程清单 skills[]）

内部事件（LLM/夜间运行/报告/评审）默认不出现在主行，
`include_internal=true` 时附带（开发者视角开关）。
前端：标题"测试活动"；recording 展开学习产出清单（链接详情页）；
test_run 展开截图墙+下钻；"显示内部事件"开关。

## 块 3：测试套件（流水线打通）

新表 test_suite / suite_run（迁移 05a4ec58c291）+ 端点：
- POST/GET/DELETE /suites（CRUD；skill 必须存在 422）
- POST /suites/{id}/run：一键执行（复用 run_replay_batch：browser
  复用 + 批级 C1 门控——不确认副作用各流程走预演）
- GET /suites/{id}/runs：执行历史

前端 /suites（侧边栏"套件"）：勾选操作流程组建 → 一键执行 →
执行汇总（通过/失败/异常/预演 + 每流程 run 链接）→ 执行历史。
真机验证：62 个流程可选 → 建套件 → 一键执行（2 流程预演）→ 汇总 → 历史。

## 块 4：概念重命名 + 仪表盘错位修复

- UI 文案：Skills→操作流程；回放→自动测试；shadow→预演；
  execute→执行（代码/API 层不动，避免破坏面）
- 仪表盘错位根因：stat-row 用 auto-fit，窄屏换行时孤卡占满整行
  （4+1 形态视觉断裂）。修复：固定列数响应式（5→3+2→2），
  换行卡始终等宽成组。1100/900px 实测等宽无孤卡。

## 测试

- server：test_suites.py +3、test_timeline.py 重构 +2、
  test_assert_eval.py toast 双通道 +1、test_visual_baseline.py 语义拆分 +1、
  test_runner_browser.py toast 轮询 +1
- web：SuitesView.spec +4、TimelineView.spec 重构、App/views 重命名适配
- 浏览器实测：s37_screenshots.py（时间线 5 步）+ s37_suite_screenshots.py
  （套件 4 步），截图入 demo/sprint37/
