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
- **MV3 SW 不热替换**：改插件后须重启常驻浏览器才生效（lessons #16）
- 品牌 Chrome 137+ 禁 `--load-extension`：自动化采集用 Playwright 自带 chromium；回放可用真 Chrome（REPLAY_CHANNEL=chrome）
- 常驻浏览器工作流：`scripts/live_browser.py 9222` + server `REPLAY_CDP_URL=http://127.0.0.1:9222` + 采集 `RECORD_CDP_URL=...`——录制/回放全程用户可见
- server 静态托管：dist 即时生效，但路由/挂载需重启 8710

## 五、踩坑速查

详见 `docs/references/project-lessons.md`（16 条）。写代码前过一遍。

## 六、文档地图

- 产品宪法：`docs/specs/2026-09-23-skilllens-mvp-design.md`
- 主计划（唯一范围基准）：`docs/specs/2026-09-24-master-delivery-plan.md`
- 原始设想：`docs/references/ai_software_learning_change_intelligence_v3.md`（43 节）
- 架构契约：`docs/arch/`；验收记录：`demo/sprintN/`；审查：`docs/reviews/`
- 代码导览：`server/README.md`、`extension/README.md`、`server/web/README.md`
