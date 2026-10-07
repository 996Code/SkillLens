# 平台化四阶段 + 全量评审 收口报告（2026-10-05 → 2026-10-07）

> 用户指令链："后续接入新系统，交互肯定有很大差异，如何让其适应" →
> "组件、链路回放和系统配对，url 匹配，油猴通配符，自动隔离" →
> "代码评审一遍，然后更新全部的文档"（评审范围升级为全库）。

## 一、平台化四阶段（全部终验 PASS）

| 阶段 | 交付 | 终验 |
|---|---|---|
| P1 交互画像 | InteractionProfile 五维组件（dropdown/modal_submit/form_fill/row_action/route_guard）随 plan 下发；executor.ts dropdown/modal 分支画像化 | JeecG 6/6 回归全绿 |
| P2 画像指纹 | fingerprint_page + detect_profile；POST /adapters/fingerprint | 工作台贴 HTML 实测（p2-fingerprint-ui.png） |
| P2.5 URL 匹配 | urlmatch.py 油猴 @match 语义；执行侧（goto URL→adapter）+采集侧（开录自动隔离） | 7/7 系统配对；插件路径 401 缺陷评审后修复复验 |
| P3 扩链 | 矩阵 52 链；skill_vars 三层换参注入；p3_record.py raw CDP 录制框架 | 52/52 全 PASS（8 系统） |
| P4 零代码接入 | firefly.yaml 纯声明 | Firefly III 学习 #291 → 插件执行 PASS |

矩阵基线：八系统 53 技能全绿；测试基线 server 504 / web 54 / extension 76。
架构契约：docs/arch/2026-10-07-platform-interaction-profile.md。

## 二、全库代码评审（2026-10-07）

范围：server/app、server/scripts、scripts/、extension/src、server/web/src 全量。
方式：三域并行深审 + 安全红线机械扫描 + 关键发现本人复核。
报告：docs/reviews/2026-10-07-full-codebase-audit.md。

### 确证违规 6 处（全部 TDD 修复）

1. 内网网关 IP 硬编码 8 处 → env 化+缺失报错（`git grep 192.168` 清零）
2. adapters 路径穿越（%5C 可越出目录任意读写）→ 白名单字符校验+穿越测试
3. executor attribution 未脱敏落库 → sanitize_error 两处补齐
4. 执行器 snapshot forms/toasts 脱敏缺口 → 与录制侧同源三重防线
5. CDP 网络证据零脱敏 → redactNetworkBody/redactNetworkUrl（net-hook 同源语义）
6. 插件自动配对 401 静默失效 → Bearer+5s 超时+401 守卫测试

### 记录不修 13 项（评审文档 §三）

私有化前置项：CORS `*`+events 豁免污染面、probes docker-exec 角色收紧。
技术债：execute() 巨型函数、events 批量 409、stale-run 误收割、AdaptersView
错误处理、token 进 URL 等——全部有入口定位，排后续需求。

### 修复后基线

server 508 / web 54 / extension 83（新增安全用例：server +2、extension +7）。

## 三、文档同步（本轮全部更新）

- 新建 docs/arch/2026-10-07-platform-interaction-profile.md（平台化架构契约）
- 新建 docs/reviews/2026-10-07-full-codebase-audit.md（全量评审报告）
- 主计划变更记录 +v2.1.1（平台化）+v2.2（全量评审）
- HANDOVER §4.1 八系统矩阵/§4.3 新基线/§2.3 技术债清单
- server/README（adapters 模块地图）、extension/README（执行协议+脱敏红线+83 用例）、web/README（adapters 路由）
- lessons #36（env fallback 红线）#37（验收路径≠真实路径）
- agents.md §四 env 变量清单+自扫命令
