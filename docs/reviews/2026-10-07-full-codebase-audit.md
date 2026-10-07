# 2026-10-07 全库代码评审（四域+安全红线）

> 范围：server/app 全部、server/scripts、scripts/、extension/src 全部、server/web/src 全部。
> 方式：三域并行深审（子代理逐文件读）+ 安全红线本人机械复核 + 关键发现本人验证后修复。
> 背景：平台化四阶段（P1 画像/P2 指纹/P2.5 URL 匹配/P3 扩链/P4 Firefly）七提交收口后的全量闸门审查。

## 一、评审结论总览

| 维度 | 结论 |
|---|---|
| 架构纪律 | C1/C2/C3 宪法执行到位；api 薄、纯函数下沉 app/ 层纪律基本执行 |
| 安全红线 | **6 处确证违规，本轮全部修复**（见下）；无 LLM key/密码泄漏 |
| 鉴权覆盖 | 21/24 router 挂 require_user；health/auth/events 豁免有注释依据 |
| 正确性 | 录制链路成熟（竞态守卫/资源清理/时序注释翔实）；执行器侧有 3 处中危隐患（记录不修） |
| 卫生 | execute() 巨型函数+fill 双拷贝是最大债务；死代码少量 |

## 二、确证违规与修复（本轮已修，全部 TDD）

### 🔴 R1 内网网关 IP 硬编码 8 处（agents.md §三红线）
`scripts/njmind_login.py:23`、`auto_record.py:20`、`live_browser.py:39`、`crud_chain_test.py:23`、`deep_chain_test.py:20`、`full_menu_test.py:21`、`multi_menu_record.py:20`、`server/app/agents/dev_executor.py:15`——`192.168.99.22` 字面量。
**修复**：全部改 env 优先（`NJMIND_LOGIN_URL`/`NJMIND_BASE_URL`/`NJMIND_DESIGNER_URL`/`NJMIND_HOST`）+ 缺失即 `sys.exit` 报错。`system.py` 的 IP→名称映射表移配置留待后续（非 key 级，低危）。

### 🔴 R2 adapters 路径穿越（任意读/写盘）
`api/adapters.py` GET/PUT `/adapters/{adapter_id}` 直接拼 `ADAPTERS_DIR`——Windows `%5C` 反斜杠解码后单段命中路由，`..%5C..%5Cevil` 可越出目录写任意 `.yaml`。
**修复**：`_check_adapter_id()` 白名单 `re.fullmatch(r"[A-Za-z0-9_-]+")`，两端点入口校验。测试 `test_adapter_id_traversal_rejected`（含实弹穿越 payload）。

### 🔴 R3 executor attribution 未脱敏（S42 红线）
`api/executor.py` 两处（goto 失败 /finish、fail/aborted/lost /finish）`str(body.evidence/summary.get("error"))[:500]` 裸落库——插件上报错误串常内嵌目标系统 URL。
**修复**：两处包 `sanitize_error()`（与 runner.py:1194 同款）。

### 🔴 R4 执行器 snapshot 三重脱敏缺口
`extension/src/background/executor.ts` snapshot forms 只有 `type==='password'` 一重防线；toasts 无 SENSITIVE_KEY_RE 过滤——录制侧 snapshot.ts 有三重（password/autocomplete/label 脱敏+toast 整条丢弃）。
**修复**：注入 JS 补齐同源三重防线（SENS 正则与 redact.ts 词表同步扩充 api_key/apikey/private_key/credential）。

### 🔴 R5 CDP 网络证据零脱敏
executor.ts `Network.getResponseBody` 100KB 响应体裸进 `observed` 落库，URL 不脱敏——登录 token 响应可明文出行。
**修复**：`shared/redact.ts` 新增 `redactNetworkBody/redactNetworkUrl`（net-hook.js 同源语义：JSON 递归敏感键掩码+urlencoded/URL query 脱敏，字符串级替换避免 URLSearchParams 编码 `[REDACTED]`），CDP 路径统一套用。

### 🔴 R6 插件自动配对 401 静默失效（P2.5 功能缺陷）
`session.ts` 裸 fetch 调 `/adapters/match`——该端点挂鉴权守卫，必 401 → catch 静默回退 njmind。P2.5 验收走服务端带 token 路径，插件真实开录路径未覆盖。
**修复**：复用 executor 的 `getToken()`（已导出）带 Bearer + 5s 超时 race。server 侧补 401 守卫测试 `test_match_api_requires_auth`。

## 三、中危项处置（同日二轮：用户指令"把该修复的都处理了"——除 2 项缓修外全部完成）

| # | 项 | 处置 |
|---|---|---|
| 1 | CORS `*`+events 豁免污染面 | ✅ 已修：events 双端点加 `X-SkillLens-Agent` 共享头守卫（CORS 收紧为非 `*` 时自动豁免）；插件三上报点带齐；测试 `test_ingest_guard_blocks_foreign_origin` |
| 2 | probes docker-exec 角色收紧 | ✅ 已修：PUT /adapters 挂 `require_role(admin,reviewer)`；viewer 403 测试。密码 env 注入改造留私有化 |
| 3 | events 批量 409 整批丢失 | ✅ 已修：逐条落库，重复键幂等跳过（`accepted/duplicates` 计数）；混合批测试 |
| 4 | executor_plan 内联后处理不可单测 | ⏸ 缓修：重构项（抽 apply_overrides 纯函数）——改动面大，需 52 链真机回归支撑，独立排期 |
| 5 | _reap_stale_runs 误标 lost | ✅ 已修：step POST 刷 `executor_state.last_step_at`，收割判据改最后步时间 |
| 6 | execute() 巨型函数+fill 双拷贝 | ⏸ 缓修：同 #4 理由——与 P1 画像覆盖面提升（Frappe 通道声明化）合并做，独立排期 |
| 7 | 执行器全局残留 | ✅ 已修：runSkill 入口统一重置 4 个 globalThis 标志 |
| 8 | debugger listener 泄漏 | ✅ 已修：具名 onEvt+finally removeListener；pendingBodies 请求结束即删 |
| 9 | AdaptersView 错误处理 | ✅ 已修：load finally+res.ok 判定；fingerprint/validate try/catch |
| 10 | SkillGraphView 竞态+blob 泄漏 | ✅ 已修：sideSeq 守卫+blob URL 全路径 revoke（含 FlowGraph onBeforeUnmount） |
| 11 | token 进 URL | ⏸ 记录：v21_matrix 脚本+executor-page（replaceState 已补救）——一次性换票属协议改造，排私有化 |
| 12 | web localStorage 存 token | ⏸ 记录：同源部署缓解，取舍已在 arch 文档明示 |
| 13 | AGENT/AGENT_URL 重复定义 | ✅ 已修：executor.ts 统一 import shared/types |

**顺手清掉的卫生项**（低危一并处理）：events/uploader 幂等语义对齐（409→跳过）、`RunHandle`/`ctxs`/`getCanvasFlow` 死代码、executor import copy 重复、adapters.py 无用 db 依赖、steps.py `expect_nick` 死分支、ARTIFACT_DIR 双常量统一进 config、llm_skills `source_of` 复用 baseline 实现、system.py njmind host 配置化（NJMIND_HOST）、cards/baseline Alignment None 守卫、popup innerHTML→textContent、uploader eventKey 加 page_id、EXECUTOR_RUN 改开 executor.html 页（SW 被杀风险根治）、idb takeEvents 游标限读、capture detached 元素 Map 清荡、session.ts /sessions 超时 race、fmtTime×5 抽 run-format、系统分组×2 抽 system-group（漂移修复）、SuitesView 删除确认+错误处理、GraphOverview sys-dot 默认色、TimelineView 缓存 LRU 上限、ReviewPortal hint 重置、api.ts login 文案分型、ReplayRunView Promise.all 并行、v21_matrix（skill_vars try 保护/ERPNext 凭据读 manifest/EXT id 动态读 dist）、p3_record（mint_token None 守卫/urllib to_thread）、live_browser profile 路径项目内+gitignore。

## 四、验证

- 一轮（红线修复）：server 506 / extension 83（新增安全用例 server +2、extension +7）。
- 二轮（中危清零）：server events/adapters/url_match 21/21 即时验证 + 全量后台跑；extension build+83/83；web 54/54+build 通过；5 个脚本 ast 语法全过。
- 三套终态基线：**server 508 / web 54 / extension 83**（events 新增 2 用例）。

## 五、对照表扬（评审沉淀的正向资产）

- `urlmatch.py`/`fingerprint.py`/`manifest.py`：纯函数、无 IO、注释与实现一致。
- auth：PBKDF2-100k + SHA-256 token 哈希 + 过期即时清理，实现与文档一致。
- 录制链路脱敏：capture→snapshot→net-hook→uploader 密码框+敏感 label 双脱敏设计完整（describe-element identity 校验是亮点）。
- sanitize_error 覆盖面：runner/runtime/canvas/gateway 全部落库点完好（本次新增 executor 两处补齐）。
