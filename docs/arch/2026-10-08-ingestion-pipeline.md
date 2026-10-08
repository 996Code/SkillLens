# 录制→学习数据管道（Ingestion Pipeline）：采集 / 上报 / 派生 / 归纳全链路

> 2026-10-08。一句话职责：**把用户在目标系统里的真实操作（点击/键入/网络请求）
> 变成可回放、可断言、可版本演化的 Skill**。全链路确定性派生，LLM 只做命名/
> 结构化（宪法 C1）；raw 数据永不删除，过滤只标记（C3）。
> 本文所有断言均可在所引 `file:line` 处核实。

## 0. 数据流总图（文字版）

```
页面事件（click/submit/input/network/navigation/snapshot）
  → capture.ts 门控+脱敏+去抖 → runtime 消息 → SW（uploader.ts）
  → IndexedDB 缓冲（store/idb.ts） → 批量 POST /sessions/{sid}/events（BATCH=50）
  → raw_event 表（幂等：UniqueConstraint(session,page,seq)）
  → POST /sessions/{sid}/process：build_windows 切窗 → classify_windows 噪声过滤
     （filtered_window 只标不删） → semantic_action（含快照归属/状态信号/toast）
     → discovered_feature 差分累加
  → POST /sessions/{sid}/field-changes：末两次 POST diff → field_change
  → POST /align（≥2 会话）：LCS 对齐 + 分桶 → alignment（skeleton/buckets/变量）
  → POST /alignments/{id}/induce：LLM 命名 + supersede 版本链 → skill/skill_strategy/evidence_edge
  → POST /skills/{id}/assertions：确定性生成 → outcome_assertion（层2/3/4）
```

## 1. 事件模型

kind 枚举六值，CS/服务端两侧同形（`extension/src/shared/types.ts:1`、
`server/app/schemas.py:11`）。全部落 `raw_event`（`server/app/models.py:25-37`）。

| kind | payload 关键字段 | 产生位置 | 消费/落库 |
|---|---|---|---|
| `action`(click) | `target`(ElementDesc)、`url`(已脱敏) | `capture.ts:258` | 窗口锚点（`windows.py:3` ANCHOR_TYPES） |
| `action`(submit) | `target`=submitter 描述（S35：非 form，form textContent 含内联脚本污染 label） | `capture.ts:270-271` | 窗口锚点；同 label click 后不另开窗（`windows.py:36-42`） |
| `action`(input) | `name`(语义键)、`value`(脱敏后)、`target` | 去抖通道 `capture.ts:160-165`；change 通道 `capture.ts:241-246` | input_variables 归纳（`variables.py:27-48`） |
| `network` | `method/url/status/duration/reqBody/resBody/error?` + `pageUrl`(发出页面) | `net-hook.js:98-101`（fetch 成功）、`:87-92`（fetch 失败）、`:124-138`（XHR）；CS 转发附 pageUrl `capture.ts:295-298` | 窗口成员、summarize_api、field_change、state_signals |
| `navigation` | `type:"page-load"`、`url`、`title`；仅顶层帧发（S42：iframe page-load 会污染目标系统派生——首条 navigation host） | `capture.ts:280-284` | 系统派生（`app/system.py`，见 S38 文档）、synthesis 页面证据 |
| `snapshot` | `phase:"before"/"after"`、`forms/labels/tables/toasts?/overflow?` | 锚点前同步 + 锚点后 2.5s 定时（`capture.ts:95-106`；IDLE_MS 2s+网络尾延迟余量）；采集 `snapshot.ts:19-46` | semantic_action.state_before/after（`process.py:50-86`）、ui_text/toast 断言 |

体积红线（`snapshot.ts:7-14`）：字段值 ≤1KB、≤50 字段（超出记 `overflow:true`）、
labels ≤20、tables ≤10、toasts ≤3×100 字符。

ElementDesc 多信号（`shared/describe-element.ts:3-15`）：`labels[]` 按优先序
（aria-label→placeholder→title→input value→文本→data-fieldname→name→表单组
label→select2 宿主 select name→宿主行文本→非框架 id），`ordinal` 结构兜底；
框架自动 id（`rc_/ant-/el-id-/pick-_pick` 等）跨会话不稳定被排除
（`describe-element.ts:195`、`input-key.ts:5`）。

## 2. 采集侧纪律

### 2.1 input 去抖与 change 双通道分级

实测根因（`capture.ts:109-113` 注释）：change 依赖 blur+dirty 标记——程序化填值
（Playwright fill 不置 dirty）与框架回显时序下不可靠，若依同一脚本两轮录制一轮丢
input 步骤导致骨架缺 fill。故 **input 事件为可靠通道**：

- input 通道：600ms 去抖发终值（`capture.ts:113,200-205`），**只滤隐藏/开关型**
  （type=hidden/checkbox/radio + CSS 隐藏，`capture.ts:118-128,198`）。picker 容器
  内可见输入不滤——zui 日期控件"计划完成"等用户直填字段在 `.pick.date-picker`
  容器内，套用容器过滤会整步丢掉 → 回放被服务端必填校验拦（`capture.ts:138-143`）。
- change 通道：**严过滤**——`isProgrammaticInput` = 隐藏/开关型 + picker 容器
  （`.picker/.ant-select/[class*=picker]/[class*=select]`，`capture.ts:134-147,219-222`）。
  禅道实测 resolution/resolvedBuild 经 change 通道泄漏（组件 UI 交互程序化同步值，
  重复 input 步会让回放 fill 隐藏 select 必抛错）。
- 双通道去重：change 收口挂起的 input 去抖（blur 即终值时刻，`capture.ts:224-228`）；
  近 2s（INPUT_DEDUP_MS）同元素同值不双发（`capture.ts:148,230-234`）；500ms 内
  同值 input 抑制（`capture.ts:159`）。
- 顺序保证：click/submit 锚点前同步 `flushPendingInputs()`（`capture.ts:256,266`），
  input 事件必先于锚点事件。
- 内存治理：detached 元素（React 重渲染换节点）30s 低频清荡两 Map（`capture.ts:176-188`）。
- 语义键回退链：name→非框架 id→placeholder→aria-label→data-fieldname（Frappe）→
  select2 宿主 select name→表单组 label（JeecG 设计器无属性 input），全空放弃
  （`shared/input-key.ts:11-19`）。

### 2.2 录制门控与幂等注入

- 门控三保险（`capture.ts:33-55`）：初始 GET_STATE 查 SW（覆盖"已开录的存量页面"）
  + `storage.onChanged` 跟随 `sl_recording`（area=local，S31：SW 被杀后 session
  存储丢失，改 local 持久化）+ 3s 兜底轮询（任一环失效则全程静默不采集）。
  `recording=false` 时 `emit` 直接 return（`capture.ts:78`）——不采集任何事件。
- 幂等注入守卫：`window.__skilllens_cs` 已置则 throw（`capture.ts:13-17`）——SW
  程序化注入（`chrome.scripting`，S42 动态 about:blank iframe 场景）可能对已注入
  frame 重复执行，重复监听器=双份事件。
- iframe 注入链：顶层帧 MutationObserver 发现 iframe → INJECT_IFRAMES → SW 对全部
  子 frame executeScript（`capture.ts:60-75`、`uploader.ts:118-129`）。
- MV3 边界：CS 与 SW 不共享 IndexedDB（CS 写页面源 DB、SW 读扩展源 DB），事件经
  runtime 消息转发、fire-and-forget，丢失由 alarms 兜底（`capture.ts:83-87`）。

### 2.3 脱敏四道 + 失败调用留痕（C3）

| 道 | 位置 | 语义 |
|---|---|---|
| ①密码框 | `capture.ts:155,239`（value→`[REDACTED]`）；`snapshot.ts:27-29`（密码框+autocomplete=password 整体跳过，宁可缺失不落掩码占位）；`describe-element.ts:205-211`（value 不进 labels，堵定位信号旁路） | 明文不出页面 |
| ②敏感 label | `redact.ts:36-45` redactValue：key/label 命中 SENSITIVE_KEY_RE（英中词表 `redact.ts:5-23`）→ 值掩码 | 表单字段名形态 |
| ③URL query | net-hook `redactUrl`（`net-hook.js:52-67`）；CS 侧 pageUrl 走 `redactNetworkUrl`（`capture.ts:29-31`、`redact.ts:63-73`，字符串级替换避免 URL API 把掩码再编码） | ?token=/?api_key= 不入 IndexedDB/raw_event/LLM prompt；host/path 不动（系统派生依赖） |
| ④请求/响应体 | `net-hook.js:10-49`：JSON 递归 redact、FormData 逐 entry、urlencoded 键值串，截断 2000 字符 | 登录 `fetch(body:JSON.stringify({password}))` 形态 |

词表四处物理副本（TS 主表/net-hook 纯 JS/executor/page_snapshot.py——CRXJS 原样
复制 injected JS 无法 import TS），漂移由 `shared/redact-parity.test.ts` 兜住。

失败调用留痕（C3）：fetch 网络层失败先 post `status:0, error:"network"` 再原样抛
（`net-hook.js:82-94`）；XHR error/timeout/abort 三事件同留痕（`net-hook.js:114-138`）。
失败分支消失会让回放对账无从判因。脱敏与成功路径同源，失败不豁免。

## 3. 上报与幂等

### 3.1 客户端（extension/src/background/uploader.ts）

- 缓冲：SW 侧 IndexedDB `skilllens/events`（`store/idb.ts:3-4`）；takeEvents 游标
  限读 batch 条、删除同事务（`idb.ts:26-45`，评审 #17：getAll 全表扫描在堆积时
  每 6s 一次全量读）。
- 触发：每条事件消息即 flush + alarms 每 0.1min 兜底（`uploader.ts:110-113,134-140,192`）；
  `flushing` 锁防并发（takeEvents 的读+删非原子，并发=重复上报，`uploader.ts:26-31`）。
- session 回填：CS 事件 `__session_id` 恒空，flush 时以活跃 sid 回填；无 sid →
  deferred 写回缓冲不丢弃不计重试（`uploader.ts:34-38,84-92`、`assign-session.ts:9-18`）。
  停止录制先 `finalFlushWithSession(sid)` 再清 storage——否则停止后 flush 读到
  null，缓冲事件永久滞留（session 0 事件根因，`uploader.ts:94-108`、`session.ts:63-70`）。
- 批量与重试：BATCH=50、MAX_RETRIES=3（`uploader.ts:12-13`）；失败回退 putEvent +
  重试计数，超限丢弃（POC 取舍，`uploader.ts:66-79`）。重试键
  `ts:seq:kind:pageId`（`uploader.ts:18-22`）——**注意：字段名疑误，见 §9**。
- 停录会话建立：popup START_RECORDING → `/adapters/match?url=` 自动配对目标系统
  （带 Bearer，401 会静默回退，评审实锤）→ POST /sessions（`session.ts:16-61`）。

### 3.2 服务端（server/app/api/events.py）

- `X-SkillLens-Agent` 守卫：CORS 默认 `*`（`config.py:24-25`、`main.py:92-97`
  allow_headers 也是 `*`）叠加本路由豁免鉴权——任意本机网页可 POST 伪造会话。
  守卫要求自定义头 `X-SkillLens-Agent:1`（`events.py:30-35`）。**威胁模型局限**：
  allow_headers=`*` 下 preflight 放行任意自定义头，恶意网页带上该头即可绕过——
  只是减速带（挡"无意识污染"，不挡蓄意伪造）；配置显式收紧 Origin 时豁免。
- 批量上限：`MAX_EVENTS_PER_BATCH=2000` → 413（`events.py:19,57-58`）。逐条 commit
  实现下超大批会把 worker 钉死数分钟；插件 BATCH=50，留 40x 余量（下限断言
  `test_events.py:83-86`）。
- 幂等：`UniqueConstraint(session_id, page_id, seq)`（`models.py:27-29`）；逐条
  commit，IntegrityError → rollback+跳过（`events.py:63-74`）。**旧语义是整批 409**
  ——一条旧 seq 让整批永久丢失（重发同错）；评审 #5 改为重复跳过、其余照常入库，
  返回 `{accepted, duplicates}`（`test_events.py:23-45`）。跨页同 seq 不冲突
  （page_id 入键，`test_events.py:48-53`）。

## 4. 派生流水线（POST /sessions/{sid}/process，`api/ingest.py:24-28`）

### 4.1 窗口切分（ingestion/windows.py）

- 参数：IDLE_MS=2000（网络间隔）、MAX_WINDOW_MS=8000（锚点起总长），随
  transaction_window 落库供对齐对账（`windows.py:1-2`、`process.py:110-113`、
  `alignment.py:8-29` 一致性快照）。
- 锚点=action 且 type∈{click,submit}（`windows.py:3,23`）；**空 label 点击不开窗**
  （S42-10：必被噪声过滤丢弃，却破坏 submit-after-click 去重的相邻性——保存 click
  与 submit 间夹 1ms 空点击 → 重复保存步进骨架 → 回放二次点击超时，`windows.py:27-30`）。
- submit-after-click 双计治理：同 label 的 click→submit 是同一用户动作，submit 不
  另开窗（否则骨架重复步、回放二次点击时页面已离开必失败）；label 不同（回车直提）
  仍开新窗（`windows.py:33-42`）。
- 跨标签页流量不入窗（S42-12）：网络事件带 `pageUrl`，与锚点页面 origin 不同则丢
  ——录制期间其他标签页后台轮询（禅道 ajaxGetMessage）带活跃 session_id 混入，
  Jeecg 技能曾学到 `/index.php` 断言、回放永假失败；无 pageUrl 的旧事件兼容保留
  （`windows.py:47-56`）。
- 窗口关闭后（idle/max 超限）其后请求视为背景流量丢弃（`windows.py:57-65`）。

### 4.2 噪声过滤——只标不删（ingestion/noise_filter.py）

四规则顺序判定（廉价先行，`noise_filter.py:73-98`）：
①`empty_label`（控制/零宽字符 strip 后为空，`noise_filter.py:29,79-80`）
②`overlong`（时长 > 2×MAX_WINDOW_MS——正常窗已被 build_windows 限长，超限=结构
异常/时钟跳变，`noise_filter.py:82-87`）
③`orphan_click`（无 network 成员且无快照——点了什么都没发生，`noise_filter.py:89-91`）
④`read_only`（有成员但全读方法且无状态信号——浏览/查询非事务，`noise_filter.py:93-96`）。

- 交互链豁免（S42-10）：orphan_click 若 3s（INTERACTION_CHAIN_MS）内紧跟下一锚点
  （picker 开下拉→选项点击），不是孤儿（`noise_filter.py:57-64,70`）。
- **C3 落库形态**：classify_windows 是纯函数；kept=False 不生成 semantic_action，
  但决策写 `filtered_window(session,window_seq,reason)` 可审计可回放重过滤
  （`process.py:114-118`、`models.py:80-87`；raw_event 永不删）。
  审计端点 GET /sessions/{sid}/filtered-windows（`ingest.py:47-55`）。

### 4.3 快照归属 + 语义动作（process.py）

- assign_snapshots：before 快照归**下一个**锚点（首个 ts≥快照 ts 的窗口，多个取最
  靠近锚点）；after 归**前一个**锚点（最后一个 ts≤快照 ts，多个取最后）；时序异常
  （末锚点后的 before/首锚点前的 after）丢弃（`process.py:50-86`）。snapshot 不进
  窗口 members——members 只含 network，混入会污染对齐骨架与 api_calls（`process.py:58-60`）。
- semantic_action 落库：anchor_seq/anchor_type/target/api_calls（summarize_api：
  seq/method/template/status/duration/params，`process.py:25-35`）/state_signals/
  state_before/state_after（`process.py:136-143`）。
- 状态信号（`signals.py:4-27`）：resBody JSON 中 `status|state|code|result`
  标量键，顶层+一层嵌套（`data.status` 网关/Frappe 包装形态；深嵌套与非标量忽略）。
- toast 信号（S12 N3 层1）：after 快照 toasts 单独 append（extract_state_signals
  只管 resBody），api 用窗口首个模板、纯 UI 窗退回锚点 label（`process.py:126-133`）。
- 中间表：normalized_event 每事件一行（模板签名 `type:label` / `METHOD:template`，
  `process.py:12-22,101-104`）；transaction_window 每窗一行（含切窗参数）。

### 4.4 字段 diff 与 field_change（fielddiff.py + fieldchange.py）

- 提取（`fieldchange.py:10-61`）：全会话 network POST 且 reqBody 可解析为 JSON
  dict，按 api_template 分组；**每模板只取末两次 POST 做 diff**（`seqs[-2],seqs[-1]`，
  `fieldchange.py:34`）。语义：低代码系统"保存"= 同模板反复 POST 全量表单，末两次
  之差≈本次流程真正改动的字段；代价：**中间态变化不可见**（A→B→C 只见 B→C），
  且 <2 次 POST 的模板无 field_change（`fieldchange.py:32-33`）。
- 入库保护：reqBody >8KB 截断存前缀+全文 sha256（`fielddiff.py:26-34`），diff 在
  截断文本上做、解析失败回退原文 body（语义降级但全文绝不入 changes，
  `fieldchange.py:37-42`）；截断标记以 `_truncated` 伪字段行进 changes JSON
  （不加列，`fieldchange.py:44-50`），断言生成时排除（`outcome.py:98-101`）。
  changes 值逐条 cap_value 8KB（`fieldchange.py:53-55`、`fielddiff.py:37-45`）。
- diff 语义：flatten 点号路径 → 排序键集并集 → 值不等即 `{field,before,after}`
  （`fielddiff.py:8-23`）。

### 4.5 发现（discovery.py，S12 N1）

- 输入：本会话 kept 的 semantic_actions（`process.py:107,144-145,150`）；候选=
  api_calls 模板 + 锚点 label，(kind,value) 去重保序（`discovery.py:21-42`）。
- 已知判定：与 `evidence_edge.dst` 全局集合差分——裸值或 `type:值` 签名任一命中
  即已知（evidence 边格式 `click:保存`/`POST:/x`，`discovery.py:45-52`、
  `process.py:149`）。
- upsert 索引：api 候选按 `api_template` 列匹配，UI 候选按 `anchor_label` 且
  api_template IS NULL（两列均有索引，`models.py:168-171`、`discovery.py:55-64`）。
- 幂等：session_id 记最近贡献会话，**同会话重 process 跳过累加**；跨会话
  observed_count+1（`discovery.py:83-89`）。已知简化：A→B→重跑 A 会再计一次
  （`discovery.py:8-9` docstring 自认）。discovered_feature 是全局累加资产，
  不随重 process 清（`process.py:147-148`、`models.py:158-164`）。

### 4.6 对齐（alignment.py，POST /align，`ingest.py:58-87`）

- 前置：2-10 个 session（`schemas.py:15-16`）；任一未 process → 409（`ingest.py:63-64`）。
- 步身份=锚点键 `type:label`；窗口签名=锚点键+`|`+排序 API 集（`alignment.py:32-55`）。
- **LCS 只按锚点键比对**（S42-9）：API 部分是窗口证据非步身份——两轮录制同一操作
  一轮窗口恰挂 GET（模态加载）一轮没有（缓存），全签名比对必丢步（禅道流转链实测，
  `alignment.py:225-227`）。每步 API 取出现会话**交集**（S34：SPA 窗口 API 集带
  偶发请求——autocomplete/轮询逐轮不同，单侧独有不进骨架，`alignment.py:186-193,270-273`）。
- 动态值归一（S43-4，`alignment.py:115-183`）：click label 命中本会话某 input 值
  （==或含，值≥3字符）→"选择刚输入/刚建的实体"；两会话同位置（±2）都判动态 →
  双侧改占位键 `click:⟨dyn⟩`（若依角色选项实测：每轮点"当轮角色名"，精确键 LCS 丢步）。
- 孤立动态对缝合（S43-4，Healenium 位置+类型相似思想）：基准侧与新侧都落单的 click，
  label ≥4 字符且含 ASCII 字母/数字（防"国内/国际"类稳定短词误缝）→ 判同一步
  （`alignment.py:240-256`）。
- 分桶（宪法 §8：分叉先分桶再桶内对齐）：锚点签名序列完全相同或 LCS 相似度
  （LCS 长/较长序列长）≥0.6 归并，贪心顺序、首入桶者作比较锚（MVP 语义，
  `alignment.py:86-112`）。每桶独立跑 `_align_one` 出桶内骨架（`alignment.py:200-209`）。
- 步产物：`{signature, session_window_seqs:{sid:窗口序号}}`（`alignment.py:274-276`）
  ——session_window_seqs 是断言生成回溯证据的精确坐标（`outcome.py:34-45`）。
- alignment 行落 skeleton/buckets/param_variables/input_variables/window_params
  （切窗参数对账快照，不一致 warn，`ingest.py:65-83`、`alignment.py:8-29`）。

### 4.7 变量抽取（variables.py）

- param_variables：骨架步各会话窗口成员 URL 路径参数（templatize 的 `{id}` 段，
  数字/UUID/32位hex，`url_template.py:4-31`）跨会话值不同 → 变量（`variables.py:4-20`）。
- input_variables：同 name 的 input 事件首值跨会话不同 → 变量，带各会话位置序号
  （`variables.py:27-48`）。

## 5. 技能归纳（learning/skill.py，POST /alignments/{id}/induce）

- **C1 边界**：LLM 只做命名——prompt 给骨架签名+变量名，只要
  `{name(PascalCase), description(中文一句话)}`（`skill.py:13-25`）；判定全确定性：
  verify_skill 校验 PascalCase + desc 非空 ≤200（`skill.py:75-82`），失败落
  candidate+notes，成功 learned（`skill.py:125-133`）。confidence 确定性公式：
  API 步占比×0.6 + 有变量×0.4（`skill.py:85-89`）。
- **parse_llm_skill 平衡括号扫描**（`skill.py:28-72`）：S27 彩排实测——思维链模型
  先输出散文且可能重复 JSON 块；贪婪 `\{.*\}` 跨块匹配非法，`\{[^{}]*\}` 拆碎
  嵌套对象。改为字符串感知（引号/转义）的深度计数扫描取全部**顶层** `{...}` 片段，
  从后往前取首个可解析非空 dict（末块通常是最终定稿）。形状无关，skill 命名/
  dev_plan/flow/generic 四处共用（`generic.py:11`、`synthesis.py:11`）。
- **空骨架分支不调 LLM**（`skill.py:103-122`）：不同锚点流不归并的合法场景，无证据
  可命名，调用只会产生幻觉名（网易实测：空骨架被命名为无关业务名）→ 直接落
  EmptyFlow candidate。该分支历史 bug：曾删旧 skill 及策略/断言，且 OutcomeAssertion
  未导入 NameError→500（该路径从未成功执行过）——现同走 supersede（`skill.py:105-107`）。
- **supersede 版本链**（S15，v3 §29 不覆盖旧版本，`skill.py:92-97,135-148`）：
  re-induce 不删旧行——旧行 `status=superseded` + `superseded_by=新行id`（已
  superseded 的行保持原链指向不变=链式指向直接后继），新行 `version=旧最大+1`；
  断言/策略只写新行，旧行断言/策略保留作历史。列表/trace 默认排除 superseded
  （`llm_skills.py:70-72`）；superseded 行 POST assertions / verify → 409 提示走
  新版本（`llm_skills.py:87-88,101-107`）。
- 策略落地：每桶一条 skill_strategy（主桶亦记录），签名=桶内骨架序列 join
  （`skill.py:149-157`、`models.py:133-141`）。
- 证据图：sync_evidence_edges 从骨架生成 `session-contains→action`、
  `action-calls→api` 边，幂等 upsert 计数累加；全局资产 re-induce 不清
  （`learning/evidence.py:1-60`、`models.py:144-155` 唯一约束 (src,dst,type)）。
- 下游延伸（同一 LLM 边界模式）：generic.py 跨系统模板归纳（slots_schema 每
  examples 值必须能在源 skill 骨架/变量/断言中子串回查到，`generic.py:63-98`；
  晋升纪律：回查通过+≥2 系统+各源 skill 最近带断言回放 PASS，`generic.py:155-179`）；
  synthesis.py 流程生成（LLM 只做目标分解，每步 target 必须在证据集合内，
  `synthesis.py:116-144`）。

## 6. 断言生成（learning/outcome.py，POST /skills/{id}/assertions）

证据范围=骨架步：只遍历 skeleton 各步 session_window_seqs 指向的 semantic_action
——单侧 session 独有的非骨架窗口（演示噪音）不得生成断言（`outcome.py:34-45`）。

| kind | 层 | 来源 | 判定语义 |
|---|---|---|---|
| api_status | 3 | 骨架窗 api_calls 中非 GET、且模板不含 reportview/search_link/search_widget/get_count/list_view/get_list（S43-4：ERPNext 查询型 RPC 虽走 POST 但语义是轮询/读取，URL 直达回放时不出现，observed None 判 fail 是假阴性，`outcome.py:47-67`） | 该模板全部命中 status == expect（`outcome.py:158-165`） |
| state_signal | 3 | 骨架窗 state_signals；GET /{id} 行读取标 `context:true` 记录不判定（回放命中行≠录制行，行属性漂移是定位语义必然，`outcome.py:68-79`） | 同模板同字段全部值 == expect（`outcome.py:166-174`） |
| ui_text | 2 | 骨架窗快照 forms 差集（同 label 值变化；空 label 跳过——无法定位必误判，`outcome.py:11-27,80-83`） | 存在性：任一窗该 label 变化即过（`outcome.py:175-191`） |
| field_change | 2 | 按 session 全量（存在性语义与骨架无关，`outcome.py:84-86`）；`_truncated` 标记行排除（`outcome.py:98-101`） | 存在性：该模板该字段发生过变化——before/after 是证据值可含输入变量，跨 session 天然不同，不作恒等条件（`outcome.py:192-206`） |

- 去重键 (kind, api_template, field|label)（`outcome.py:106-112`）；畸形证据
  （非 dict/缺键）跳过并 logger.warning——C3 可见不吞，不得 KeyError（评审 #7，
  `outcome.py:54-60,91-97,154-157`）。
- 层4 历史成功样本是资产：重建前按签名快照 evidence_count、重建后回填；≥3 在
  payload 标 `layer4_verified`（`outcome.py:114-135`）。verify 通过累加放 **API 层**
  （保持库函数纯查询零写；回放评估走独立 assert_eval 路径，`llm_skills.py:109-118`）。

## 7. 重跑与幂等边界

process_session 先删本 session 的四张派生表再重建：normalized_event /
transaction_window / semantic_action / filtered_window（`process.py:98-99`）。
**不删**的全局资产：discovered_feature、evidence_edge（累加语义，
`process.py:147-150`、`discovery.py:7-9`）。field_change 由独立端点重跑、同样
先删后建（`fieldchange.py:28`）。outcome_assertion 重建时 evidence_count 回填保留
（`outcome.py:114-131`）。skill 不删旧行只 supersede（§5）。
raw_event/recording_session 任何路径都不删——重过滤/重派生的最终兜底（C3）。

## 8. 数据模型速查

| 表 | 关键列 | 索引/约束 | 谁写 | 谁读 |
|---|---|---|---|---|
| recording_session | source(demo\|real_traffic)、target_system、note | PK id(uuid) | events.py:45-51 | 全链路 404 校验、C2 展示分轨 |
| raw_event | session_id/page_id/seq/ts/kind/payload | uq(session,page,seq)；session_id idx | events.py:54-74 | process/fieldchange/align/synthesis |
| normalized_event | event_id/template | session_id idx | process.py:101-104 | 审计/图化 |
| transaction_window | anchor_event_id/member_event_ids/idle_ms/max_window_ms | session_id idx | process.py:110-113 | collect_window_params 对账 |
| filtered_window | window_seq/reason | session_id idx | process.py:116-117 | GET filtered-windows 审计 |
| semantic_action | anchor_seq/type/target/api_calls/state_signals/state_before/after | session_id idx | process.py:136-143 | align 前置校验、outcome、API 列表 |
| field_change | api_template/before_seq/after_seq/changes | session_id idx | fieldchange.py:56-58 | outcome 层2 |
| discovered_feature | api_template/anchor_label/observed_count/status | 两列各 idx | discovery.py:77-89 | GET /discoveries、N2 confirm |
| alignment | session_ids/skeleton/buckets/param_variables/input_variables/window_params | — | ingest.py:78-83 | induce_skill |
| skill | alignment_id/name/status/version/superseded_by/confidence/skeleton | alignment_id idx | skill.py:139-148 | 列表/回放/套件 |
| skill_strategy | skill_id/strategy_signature/skeleton/evidence_count | skill_id idx | skill.py:155-157 | 回放多路径 |
| evidence_edge | src/dst/type/evidence_count | uq(src,dst,type) | evidence.py:31-42 | discovery 已知集合、影响分析 |
| outcome_assertion | skill_id/layer/kind/api_template/payload/evidence_count | skill_id idx | outcome.py:129-135 | 回放评估、verify |
| generic_skill | slots_schema/status/source_skill_ids | — | generic.py:126-130 | 通用能力层 |
| llm_call_log | purpose/prompt/response/latency_ms | — | llm/gateway.acomplete | 排障（先查实际输入，AGENTS.md §二） |

（模型定义均见 `server/app/models.py`，行号略。）

## 9. 已知债务与缓修项（代码确证）

1. **重试键 pageId 字段名疑误**：`uploader.ts:21` 取 `e.pageId`，而 RawEvent 字段是
   `page_id`（`types.ts:5`）——运行期恒 undefined，键的 page_id 段恒空串。注释声称
   "page_id 必入键（评审 #14）：不同 frame 同毫秒同类型事件键碰撞会互相污染重试
   计数"，实际该防护未生效（vite 构建不做类型检查所以未报编译错）。影响面：仅重试
   计数去重，服务端幂等由 DB 唯一约束兜住，不致数据损坏。
2. **C2 学习轨道未分轨**：source 只在 recording_session 打标（`models.py:21-22`）
   与列表展示（`llm_skills.py:55,78`）；process/align/induce 全不按 source 过滤
   ——demo 与 real_traffic 会话可混入同一 alignment 归纳。
3. **skill_id/alignment_id 无外键级联**：outcome_assertion.skill_id（`models.py:298`）、
   skill_strategy.skill_id（`models.py:137`）、skill.alignment_id（`models.py:116`）
   均为裸 int+索引，删行留孤儿靠上层纪律（S15 后不删 skill 缓解）。
4. **DateTime 列未带 timezone**：默认值 `utcnow()` 是 aware datetime
   （`models.py:11-12`），但列类型未声明 `DateTime(timezone=True)`——SQLite 存
   naive，跨库迁移/比较语义依赖约定。
5. **alignment O(n²)+**：`_align_one` 主循环内每轮迭代重建配对集合
   `{(a,b) for a,b in pairs}`（`alignment.py:232`）；分桶后每桶全量过滤 keyed
   重建输入（`alignment.py:207`）。会话数/窗口数小（≤10 session）暂无感。
6. **服务端写路径无二次脱敏兜底**：events.py 将 payload 原样入库
   （`events.py:66-67`），四道脱敏全在客户端——绕过插件直接 POST（带守卫头）可存
   敏感明文；llm_call_log 异常摘要有 URL 脱敏，raw_event 没有对应兜底。
7. **客户端超限丢弃与 C3 张力**：重试 >3 丢事件（`uploader.ts:71-75` 自注 POC
   取舍）、finalFlush 无 sid 的 deferred 直接丢弃（`uploader.ts:102-104`）——采集侧
   链路存在合法丢失窗口，"全链路落库"以到达服务端为界。
8. **field_change 末两次 POST 语义盲区**：中间态变化不可见、单次 POST 模板无
   field_change（§4.4）；`fieldchange.py:14` 类型注解 `list[tuple[int,dict]]` 与
   实际 append 的三元组不符（`fieldchange.py:26`，注解失真非运行 bug）。
9. **discovery 计数已知简化**：A→B→重跑 A 再计一次（`discovery.py:8-9` 自认）。
10. **任务口径澄清**：管道内无 `ingestion/perf.py`/`ingestion/evidence.py`——perf
    在 `app/change/perf.py`（回放耗时漂移，属回放侧非录制派生），evidence 在
    `app/learning/evidence.py`（§5 已述）。

## 10. 测试覆盖地图

| 语义 | 测试 |
|---|---|
| 事件模型/幂等/守卫/413 | `server/tests/test_events.py`（重复跳过:23、混合批:35、跨页同 seq:48、403 守卫:56、413:70、余量下限:83） |
| 采集/去抖/门控 | `extension/src/content/capture.test.ts`（9 例）、`capture-redact.test.ts`（4 例） |
| 快照体积/脱敏 | `extension/src/content/snapshot.test.ts`（9 例） |
| net-hook 成功/失败留痕 | `extension/src/injected/net-hook.test.ts`（8 例） |
| 脱敏词表四处一致 | `extension/src/shared/redact.test.ts`（25 例）、`redact-parity.test.ts`（6 例） |
| 切窗（idle/max/submit 去重/跨标签页） | `server/tests/test_windows.py`（:11,:26,:37,:42,:66,:91,:105,:119） |
| 噪声四规则+交互链豁免+只标不删 | `server/tests/test_noise_filter.py`（:34-:98 规则、:143 process 集成、:161 幂等、:196 豁免、:233 空 label 不开窗） |
| process 全链/快照归属/toast | `server/tests/test_process.py`（:19,:38 幂等,:51 中间表,:117 快照,:141 多 after 取末,:164,:189） |
| 状态信号 | `server/tests/test_signals.py`（顶层/嵌套/深层忽略/njmind code 约定） |
| fielddiff/截断/性能 | `server/tests/test_fielddiff.py`（:24 端点、:66 截断、:117 8192 边界、:127 100KB 性能） |
| discovery 差分/幂等/confirm | `server/tests/test_discovery.py`（:31,:50,:62,:73,:91,:116,:137） |
| 对齐/LCS/分桶/动态归一/缝合 | `server/tests/test_alignment.py`（:16-:115 基础+分桶、:115 ⟨dyn⟩、:139 缝合） |
| 变量 | `server/tests/test_variables.py`（:8,:23,:36,:43） |
| skill 归纳/版本链/parse | `server/tests/test_skill.py`（:32 learned、:44/:54 candidate、:64/:75/:112 supersede 链、:192 策略+证据、:277/:339 空骨架不调 LLM、:308-:331 parse_llm_skill） |
| 断言生成/层4/畸形容错 | `server/tests/test_outcome.py`（:53 仅骨架、:150 ui_text、:175 toast、:202 层4、:241 _truncated、:277 计数保留、:295/:308 畸形不 raise） |
