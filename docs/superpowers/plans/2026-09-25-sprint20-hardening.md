# Sprint 20 交付加固 Implementation Plan（块 J，M4 启动）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划块 J（J2-J5；J1 全闭环贯通依赖 G4 试点，暂缓）。

**Goal:** 交付前的工程加固——PII 脱敏规则配置化（J4，SWOT/S-2）、备份恢复演练（J3）、性能收尾（J5：镜像瘦身+100KB diff 基准）、安装向导打磨（J2）。

**Tasks:**
1. **J4 PII 规则配置化**（TDD）：`PII_PATTERNS` env（逗号分隔正则，追加到插件 SENSITIVE_KEY_RE 与 server redact 词表）+ server 侧响应体脱敏应用点核查；测试：自定义正则命中脱敏。
2. **J3 备份恢复演练**：deploy/README 补恢复步骤 + 实际演练（volume 备份→恢复→health+数据核对）——本机 Docker 实测。
3. **J5 性能**：Dockerfile 瘦身（多阶段构建/chromium 依赖裁剪评估）+ reqBody 100KB diff 基准测试（已有 8KB 截断，补性能断言）。
4. **J2 安装向导**：deploy/README 重写为向导式（步骤编号+预期输出+故障排查表）。
5. 仪式收尾：全量三套→审查→文档→合并。

**Global Constraints:** 测试基线 275/28/34；安全红线（PII 配置本身不含真实值）；仪式全流程。
