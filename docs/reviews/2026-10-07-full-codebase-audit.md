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

## 三、记录不修（中危，排后续需求）

1. **CORS `*` + events 豁免叠加**：任意网页可向 127.0.0.1:8710 POST /sessions 污染录制数据（C2 分轨污染面）。部署边界既定（本地/127.0.0.1），私有化收紧指引已有——私有化前必须处理。
2. **probes docker-exec 任意 shell**：manifest 提供的 shell 直跑 `sh -c`，PUT /adapters 仅 viewer 角色即可写盘——"adapters 写盘限 reviewer/admin" 角色收紧 + 密码 env 注入改造，排私有化前置项。
3. **events 批量 409 整批回滚**：一条旧 seq 让整批事件永久丢失（重发同错）。逐条降级或预查重。
4. **executor_plan 113 行内联后处理**：URL 归一/换参注入等确定性变换不可单测，违纯函数纪律——抽 `apply_overrides()` 纯函数（重构项）。
5. **_reap_stale_runs 用 created_at 判超时**：慢步骤/确认停留 >10min 的 run 误标 lost——心跳时间戳入 executor_state。
6. **execute() 巨型函数+fill 双拷贝漂移**：重构项（op handler 拆分+fillDOM 抽取），与 P1 画像覆盖面提升（Frappe 通道声明化）合并做。
7. **执行器全局残留**：`__ip/__getItemsDone/__lastSearchValue` 写后不清——runSkill 入口统一重置（小改，可随下轮顺手）。
8. **debugger onEvent listener 不移除**：多轮执行监听器累积泄漏——finally 清理（同上）。
9. **AdaptersView 错误处理缺失**：load() 无 finally、fingerprint/validate 不判 res.ok——500 时卡"加载中"/错误体当结果渲染。
10. **SkillGraphView 侧数据竞态+blob 不 revoke**：快速切换流程时旧数据晚到覆盖；fetchVisualImage blob URL 泄漏。
11. **token 进 URL**（v21_matrix.py executor.html?token=、executor-page.ts URL 参数+replaceState）：浏览器历史/CDP 记录残留面——短期可接受，长线改一次性换票。
12. **web api.ts localStorage 存 token**：XSS 可窃取（同源部署缓解）——arch 文档明示取舍。
13. **`AGENT`/`AGENT_URL` 重复定义**：executor.ts 自持一份,统一 import（卫生）。

## 四、验证

- server：adapters_api 7/7、url_match 6/6、sanitize、fingerprint、manifest 全过；全量 506 passed（504 基线+评审新增 2 安全用例）。
- extension：build 通过 + vitest 83/83（含新增 7 个网络脱敏用例，新基线 76→83）。
- web：54 用例未动（本轮无 web 代码变更——AdaptersView 缺陷记录待修）。

## 五、对照表扬（评审沉淀的正向资产）

- `urlmatch.py`/`fingerprint.py`/`manifest.py`：纯函数、无 IO、注释与实现一致。
- auth：PBKDF2-100k + SHA-256 token 哈希 + 过期即时清理，实现与文档一致。
- 录制链路脱敏：capture→snapshot→net-hook→uploader 密码框+敏感 label 双脱敏设计完整（describe-element identity 校验是亮点）。
- sanitize_error 覆盖面：runner/runtime/canvas/gateway 全部落库点完好（本次新增 executor 两处补齐）。
