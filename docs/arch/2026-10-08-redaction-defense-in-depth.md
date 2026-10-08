# 脱敏纵深防御（Redaction Defense-in-Depth）：从密码框到 LLM 归因 prompt

> 2026-10-08。安全红线"凭据/PII 永不落库、永不进 prompt"的**全链路实现地图**。
> 本文回答三个问题：敏感数据可能从哪些通道进来？每条通道上有哪些防线？防线之间如何保证不漂移？
> 来源：三轮评审 R3-6/R3-9 与二轮 R4/R5 的修复沉淀；一致性由测试守护而非口头纪律。

## 1. 威胁模型：敏感数据的六条入口通道

| # | 通道 | 载体 | 下游 |
|---|---|---|---|
| 1 | 密码框输入 | `input[type=password]` 的 value | IndexedDB → raw_event → LLM |
| 2 | 敏感 label 的普通输入框 | label/name 含"密码/api_key"的 text 字段 | 同上 |
| 3 | 网络 URL query | `?token=…&api_key=…`（登录回跳、API 调用） | 同上 + plan 落库 |
| 4 | 网络请求体 | `fetch(url,{body:JSON.stringify({password})})`、urlencoded 表单 | 同上 |
| 5 | 网络响应体 | 登录接口响应（token/session） | 同上 |
| 6 | 文档 URL | `location.href`（SSO 回跳 `?ticket=`）与错误文本内嵌 URL | 快照/error → 落库 + prompt |

目标系统是中文业务系统（禅道/JeecG/若依/njmind），词表必须同时覆盖英文 key 形态与中文
label 形态（密码/口令/密钥/令牌/凭证/验证码）。

## 2. 防线地图（按数据流顺序）

```
页面 ──capture.ts──► IndexedDB ──uploader──► /events ──► raw_event ──process──► 派生表
   └─net-hook.js（MAIN world）─┘                                   └─runner/executor──► ReplayRun + LLM prompt
   └─snapshot.ts（CS world）──┘
```

### 2.1 采集侧（插件，四道防线，通道 1-5）
- **密码框整体跳过**（连 label 都不落）：`content/snapshot.ts`、`replay/page_snapshot.py`
  （服务端同源）、executor 页内快照（`executor.ts` 注入 JS）。
- **敏感 label 值脱敏**：`shared/redact.ts redactValue` + `buildSensitiveRe`（J4 留扩展通道）。
- **URL query 脱敏**：`redactNetworkUrl`（字符串级替换，避免 URLSearchParams 编码 `[REDACTED]`）。
- **请求/响应体递归脱敏**：`redactNetworkBody`（JSON 递归敏感键掩码）+ urlencoded 形态
  （`net-hook.js redactFormString`）；FormData 字符串值参与、文件对象置 `[FILE]`。
- **toast 整条丢弃**（敏感 toast 宁缺勿漏）+ 表单值 SENS 检测（`executor.ts` 页内 `SENS`）。

### 2.2 文档 URL 与错误文本（通道 6，三轮补齐）
- 录制事件：`capture.ts:29 pageUrl()` = `redactNetworkUrl(location.href)`——click/submit/
  page-load/network 四类事件统一走它；**host/path 不动**（目标系统派生依赖首条 navigation 的 host），
  只掩 query 中的敏感参数。
- 执行快照：`executor.ts` 页内表达式无法 import，快照 `page.url` 在 **SW 侧**收到证据后补一道
  `redactNetworkUrl`。
- 错误文本：服务端 `replay/sanitize.py sanitize_error()`（URL→`<url>`）统一套在 runner 步骤 error、
  归因 prompt、executor /finish 两处 attribution、flow_runner execution_log——
  gateway 只脱敏 failure 摘要，**success 场景的 prompt 原文入 llm_call_log**，所以入库前必须先脱。

### 2.3 服务端兜底（纵深第二层）
- `page_snapshot.py`：与插件同词表 + 同限额（≤50 字段/值 ≤1024 字符），密码框整体跳过，
  **全部 frame 聚合但限额是全局总量**。
- `config.PII_PATTERNS`（env 逗号分隔）追加私有化自定义敏感字段——仅服务端快照侧生效。
- adapters 清单：GET yaml 回显打码（§4）。
- **已知缺口（记录项 C4）**：events 写路径（`payload` 原样落库）与 fieldchange 无服务端二次
  脱敏——插件漏一个字段即明文入库；缓修理由：脱敏后的值无法用于回放注入，属产品取舍。

## 3. 词表四处物理副本与一致性测试（R3-6）

**为什么会有四份**：① `extension/src/shared/redact.ts`（TS 正典）② `extension/src/injected/net-hook.js`
（MAIN world 纯 JS——CRXJS 对 `web_accessible_resources` **原样复制不做 TS 转换**，不能 import）
③ `server/app/replay/page_snapshot.py`（服务端 Python）④ `executor.ts` 页内注入的 `const SENS`
（注入代码不能 import）。副本无法消除 → **漂移必须让 CI 失败**：

`extension/src/shared/redact-parity.test.ts`（`@vitest-environment node`）：用 `import.meta.url`
读四处源码文本 → 正则提取（TS/JS 正则字面量）与引号列表提取（Python 列表）两种解析器 →
断言四处词集相等 + 中文六词覆盖 + 词表无重复。当前 16 词：
`password/passwd/secret/token/authorization/cookie/api_key/apikey/private_key/credential/
密码/口令/密钥/令牌/凭证/验证码`。

**修改词表的唯一正确流程**：改 `redact.ts` 正典 → 同批改另三处 → parity 测试绿了才算完。
漏改任何一处，`npx vitest run src/shared/redact-parity.test.ts` 直接红。

## 4. 适配器清单的掩码回填（R3-9，"安全修复反毁凭据"教训）

问题链：GET `/adapters/{id}/yaml` 为防凭据回显做了打码（`manifest.py redact_manifest_text`，
敏感键值→`***`）→ web 编辑器的真实路径是 **GET 回显 → 用户改两行 → PUT 原文** →
`***` 被原样写回磁盘，**一次保存即销毁演示容器凭据**。

解法 `manifest.py:318 restore_masked_secrets(new_text, old_text)`：
- **行级 FIFO 回填**：解析旧文本同名敏感键值队列，新文本中仍是 `***` 的行按出现序回填旧值——
  不重序列化，**保留用户注释**；同名键多次出现按序配对。
- **显式编辑优先**：用户真改了口令（该行已不是纯 `***`）→ 保留新值。
- `api/adapters.py::save_adapter`：读旧文本 → 回填 → pydantic 校验 → 写盘（写的是回填后的文本）。
- 直测：`test_adapters_api.py` 回显往返保留原口令 / 显式改写覆盖掩码 两例。

**通用教训**：任何"读-改-写"编辑器上叠加脱敏回显，都必须配掩码回填；只做打码的安全修复
会在第一次保存时变成数据破坏。

## 5. 注入页内 JS 的模板串转义陷阱（R3-7）

executor.ts 通过 `Runtime.evaluate({expression: \`…\`})` 把 JS 注入页面执行。写在反引号模板串
里的 `\s` 会被 TS 编译成**字面 s**（少一层转义）：`/[*\s]/g` 到页面成了 `/[*s]/g`——
把 label 里每个字母 s 剥掉，匹配必失败。同型坑：`'\n'` 到页面成了**真实换行** = 语法错误。

规则：**注入表达式内所有转义一律双写**（`\\s`、`\\n`），并由
`executor-injected-regex.test.ts` 扫描全部 `expression: \`` 模板串断言零单反斜杠转义
（自带非空守卫：表达式计数 ≥10 且含锚点字面量，防实现改名后测试空转）。

## 6. 失败调用同样脱敏（C3 × 红线）

`net-hook.js` 本轮补齐失败路径留痕（fetch reject / XHR error/timeout/abort →
`{status:0, error:"network|timeout|abort"}`）——**失败事件的 URL/请求体同样过
`redactUrl`/`redactReqBody`**：红线不因失败而豁免。

## 7. 测试覆盖地图

| 防线 | 测试 |
|---|---|
| 词表四处一致 | `extension/src/shared/redact-parity.test.ts`（5 例） |
| 文档 URL 脱敏（host/path 保留、敏感参数掩码） | `capture-redact.test.ts`（4 例，jsdom stub location） |
| 网络 URL/body（成功+失败路径） | `net-hook.test.ts`（8 例） |
| 密码框/敏感 label/快照限额 | `snapshot.test.ts`、`capture.test.ts`、`page_snapshot` 相关 server 测试 |
| 注入转义 | `executor-injected-regex.test.ts`（3 例 + 非空守卫） |
| sanitize_error 全落库点 | `test_replay_failure.py`、executor attribution 测试 |
| 掩码回填 | `test_adapters_api.py`（2 例） |
| **缺口** | 服务端 events 写路径二次脱敏无测试（未实现，C4）；`redact.ts` 中文词例已有、`PII_PATTERNS` 扩展通道无用例 |
