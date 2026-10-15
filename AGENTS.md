# SkillLens 项目工作规范（所有贡献者/子代理必读必守）

> 本文件是项目的"操作宪法"——由 2026-09-24/25 实践沉淀，用户确认固化。与 `docs/specs/2026-09-23-skilllens-mvp-design.md`（产品宪法）和 `docs/specs/2026-09-24-master-delivery-plan.md`（主计划）配套：产品冲突以宪法为准，范围冲突以主计划为准，流程以本文件为准。

## 一、阶段闸门仪式（每个 Sprint/阶段完成必走，缺一不可）

```
① 三套测试全绿 → ② 代码审查（耦合+安全） → ③ 文档补全
→ ④ 浏览器用户层实测（界面设计+易用性，截图入库） → ⑤ 用户测试报告入库
→ ⑥ 合并 main + 删分支 + 清工作区 → ⑦ 才可开下一阶段
```

1. **三套测试**（全绿才算完成，"能跑"≠"测过"）：
   - server：`cd server && uv run pytest -q`（当前基线见主计划）
   - web：`cd server/web && export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH" && npm test`
   - extension：`cd extension && export PATH=... && npm run build && npm test`
2. **代码审查**：新代码不得与现有实现不当耦合（纯函数优先/最小侵入/全调用方破坏面核实）；安全红线逐条扫（见§三）。
3. **文档补全**：新模块必须有架构/契约文档（docs/arch/）；README 导览同步更新；阶段验收记录入 demo/sprintN/。
4. **浏览器用户层实测**：以真实用户路径操作（非只跑单测），检查界面设计与功能易用性/可用性；**截图存 demo/sprintN/screenshots/**；发现的问题分级记录并转后续需求。
5. **用户测试报告**：demo/sprintN/user-test-report.md，含截图引用与易用性发现表。
6. **合并**：本地合 main + 删分支 + 清工作区（uv.lock 被本机镜像改写属正常，还原勿提交）。

## 二、开发纪律

- **TDD 先红后绿**：任何功能先写失败测试再实现；新功能必配新用例。
- **测试即规格**：brief 与测试矛盾时以测试为准，最小修正并记录。
- **计划纪律**：计划外功能/范围变更必须先进主计划（修订+变更记录）获用户确认，再动手。方向授权 ≠ 计划变更权。
- **E2E 修复轮预留**：浏览器/插件类工作单测通过≠真实可用，计划预留 1-2 轮真机修复。
- **LLM 产物排查**：先查 llm_call_log 实际输入，别先怪模型。
- **成熟项目对照（强制）**：动手写实现/修 bug 前，先查同类问题的成熟 harness 怎么解——目标系统官方测试套件优先（容器内一手源码，如 Frappe 的 cypress/support/commands.js、Odoo 自己的 tour/test 套件），其次 Playwright/Healenium 等基础设施库源码；本地容器/仓库 > 官方文档 > 搜索文章（一手优先）。结论落到代码前注明出处模式（如 "Frappe save 命令 = intercept+wait"）。S43-4 实证：checkbox 勾选（官方普通 click 非独占 check）、提交判定（等写请求非解析 toast 文案）都直接来自官方 harness。
- **宪法约束**：C1 影子模式零例外；C2 真实流量标记分轨；C3 全链路落库（含失败调用）；LLM 只做命名/结构化/归因，判定全确定性。

## 三、安全红线（任何代码/测试/文档/提交/日志不得出现）

- 真实 LLM key、网关域名、njmind 凭据（.env 已 gitignore，永不打印/提交）
- llm_call_log 异常摘要必须 URL 脱敏（已实现，勿回退）；插件侧密码框+敏感 label 双脱敏
- 提交前 diff 扫敏感串（sk-/密码值/域名）

## 四、环境要点（Windows 开发机）

- Node：系统 22.10 过旧，extension/web 命令前缀 `export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"`
- vite 已 pin ~8.2.2（8.3.0 Windows 回归）；npm 缺 win32 绑定：`npm i @rolldown/binding-win32-x64-msvc --no-save`
- Playwright 浏览器：`PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright uv run playwright install chromium`
- uv.lock 镜像重写：提交前 `git checkout -- server/uv.lock`
- 杀端口：`powershell -NoProfile -ExecutionPolicy Bypass -File D:/tmp/kill_8710.ps1`（Git Bash 里 `$_` 会被吞，一律用 ps1 文件）
- **njmind 内网地址只入 server/.env，永不入库**（2026-10-07 评审清零：脚本 env 缺失一律报错退出，不写 fallback）：`NJMIND_LOGIN_URL`/`NJMIND_BASE_URL`/`NJMIND_DESIGNER_URL`/`NJMIND_HOST` + `NJMIND_USER`/`NJMIND_PASS`；提交前 `git grep 192.168` 自扫
- **MV3 SW 不热替换**：改插件后须重启常驻浏览器才生效（lessons #16）
- 品牌 Chrome 137+ 禁 `--load-extension`：自动化采集用 Playwright 自带 chromium；回放可用真 Chrome（REPLAY_CHANNEL=chrome）
- 常驻浏览器工作流：`scripts/live_browser.py 9222` + server `REPLAY_CDP_URL=http://127.0.0.1:9222` + 采集 `RECORD_CDP_URL=...`——录制/回放全程用户可见
- server 静态托管：dist 即时生效，但路由/挂载需重启 8710

## 五、踩坑速查

详见 `docs/references/project-lessons.md`（**#1-#59**，持续追加）。写代码前过一遍——每条都有实证出处。

## 六、文档导航（唯一入口——按任务找文档）

> **本文档是 AI/新成员的起点与目录**：读这一节就能定位任何文档。
> 起点顺序：本文件 → `docs/HANDOVER.md`（继任任务书）→ `PROJECT-GUIDE.md`（详细导览）。

### 6.1 三份根文档

| 文档 | 作用 |
|---|---|
| `agents.md`（本文件） | 操作宪法+文档导航——AI 协作必读必守 |
| `README.md` | 产品门面（能力/快速开始/演示） |
| `PROJECT-GUIDE.md` | 详细导览（是什么→在哪→怎么跑→怎么继续开发） |

### 6.2 治理与交接

| 文档 | 作用 |
|---|---|
| `docs/HANDOVER.md` | **继任开发任务书**：现状一句话→v2.1→v2.8 演进账本→差距清单（下一步工作）→环境速查→已知坑→提示词套件（§8） |
| `docs/COLLABORATION-CHARTER.md` | 项目所有者全部要求汇总（传承文档） |
| `docs/specs/2026-09-23-skilllens-mvp-design.md` | 产品宪法（三条：C1 影子/C2 分轨/C3 落库） |
| `docs/specs/2026-09-24-master-delivery-plan.md` | **主计划（唯一范围基准）**——§7 变更记录=完整演进史（v1.0→v2.8.4） |
| `docs/RELEASE-CHECKLIST.md` | 发布清单 |

### 6.3 设计规格（specs/，按块）

| 文档 | 块 |
|---|---|
| `docs/specs/2026-10-09-ak-exception-convergence-design.md` | AK 执行引擎异常收敛层（四码/预算/熔断/swallow，含批次落地记录） |
| `docs/specs/2026-10-10-am-expectation-anomaly-detection.md` | AM 期望-观测对比异常检测（写水位/登录守卫/三态呈现） |
| `docs/specs/2026-10-10-an-cross-step-state.md` | AN 跨步状态传递（pickedRow/${stepN.row}/row_anchor_from，含两轮 E2E 记录） |
| `docs/specs/2026-10-15-ar-management-closed-loop-redesign.md` | **AR 下一冲刺**：Scenario→ScenarioRun→自动报告→评审闭环；高级工具上下文化；六批执行计划 |
| 其余 specs | 各历史块设计（AA 图基座/AE 多角度闭环/AH 空间面板/AI 日常化/AJ 异常分类学等） |

### 6.4 架构契约（arch/，25 篇——改模块前读对应篇）

| 关键篇 | 覆盖 |
|---|---|
| `docs/arch/2026-10-08-replay-engine.md` | 回放引擎（定位/换参/断言/自愈全链） |
| `docs/arch/2026-10-08-adapters-subsystem.md` | 适配器子系统（YAML 清单/探针/画像） |
| `docs/arch/2026-10-08-auth-and-role-matrix.md` | 认证与角色矩阵（WRITE_GUARD 31 端点） |
| `docs/arch/2026-10-08-redaction-defense-in-depth.md` | 脱敏纵深（词表四处副本+parity 测试） |
| `docs/arch/2026-10-08-ingestion-pipeline.md` / `docs/arch/2026-10-08-change-intelligence.md` / `docs/arch/2026-10-08-env-contract.md` / `docs/arch/2026-10-08-schema-migration-discipline.md` | 采集管道/变更智能/env 契约/迁移纪律 |
| `docs/arch/extension-executor-protocol.md` | 插件执行协议（四端点/幂等/心跳） |
| `docs/arch/2026-10-07-platform-interaction-profile.md` | 平台化交互画像 |
| 其余 | 各历史块架构（图基座/评审门户/时间线/视觉回归等） |

### 6.5 参考与教训（references/）

| 文档 | 作用 |
|---|---|
| `docs/references/project-lessons.md` | **踩坑速查 #1-#59**（写代码前过一遍——每条都是实证） |
| `docs/references/ai_software_learning_change_intelligence_v3.md` | 原始设想（43 节） |
| `docs/references/harness-study-v2-*.md`（6 篇） | 业界调研（zcode/Playwright/Cypress/TestRail/mabl/selfheal——AJ/AM 块的依据） |
| `docs/references/zcode-browser-harness-study.md` | zcode 浏览器层精读（executor 六根因的出处） |

### 6.6 审查与验收

| 位置 | 内容 |
|---|---|
| `docs/reviews/2026-10-10-robustness-audit.md` | 最新健壮性体检（🔴🟡全清记录） |
| `docs/reviews/`（10 篇） | 历次审查（全库三轮/差距分析/竞品对标/风暴复盘 2026-10-09-attach-storm-retrospective.md） |
| `demo/sprint44/` | 最新验收（换参矩阵+315/303 终验）；更早见 `demo/` 下各 sprint 目录 |

### 6.7 代码导览

`server/README.md`（模块地图+exec 层）、`extension/README.md`（含 shared 新模块：budget/failures/expectations/chain-rules）、`server/web/README.md`

### 6.8 快查：我想做什么 → 读什么

| 任务 | 入口 |
|---|---|
| 接手开发 | HANDOVER §3 差距清单+§8 提示词套件 |
| 改回放/执行 | arch/replay-engine + specs/AK+AM 设计 |
| 加新系统 | arch/adapters-subsystem + PROJECT-GUIDE 接入章 |
| 修 bug | lessons（先查同坑）→ 对应 arch 篇 |
| 查历史决策 | 主计划 §7 变更记录（带 commit 号） |
| 跑测试/起环境 | 本文件 §一/§四 |
