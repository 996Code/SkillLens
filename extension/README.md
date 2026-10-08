# SkillLens Extension 代码导览

> Chrome MV3 采集插件（Sensor）+ 执行节点（Executor）：采集只采集不判断；
> 执行走 chrome.debugger CDP 桥接（AG3/AG5 定局：插件=完整执行节点）。
> 构建产物 `dist/` 以开发者模式加载。

## 快速开始

```bash
cd extension
npm install                     # Windows 首装若缺 @rolldown/binding-win32-x64-msvc → npm i 该包 --no-save
npm run build                   # 产物 dist/（chrome://extensions 开发者模式加载）
npm test                        # vitest（jsdom）
```

Node 要求 ≥22.12（vite 8；Windows 用便携版 Node 24 前缀 PATH）。vite 已 pin `~8.2.2`（8.3.0 Windows config 加载回归）。

## 模块地图（src/）

```
manifest.config.ts   MV3 manifest（CRXJS）
popup.html/popup.ts  录制开关 UI：开始/停止/状态点（录制红脉冲/Agent 连接态）
background/
  session.ts         SW：会话管理 + 录制标记（storage.local 持久化——SW 重启
                     自动恢复）；P2.5 开录时活动页 URL→/adapters/match 自动
                     配对系统（带 Bearer——该端点在鉴权守卫后）
  executor.ts        SW：执行器主体（chrome.debugger CDP 桥接；探针准入/
                     双通道点击/P1 画像解释——interaction_profile 驱动
                     dropdown/modal_submit 特化；zcode 模式移植）
  uploader.ts        SW：事件缓冲（IndexedDB）+ 批量上报 → http://127.0.0.1:8710/api/v1
content/
  capture.ts         CS：事件采集（action/network/navigation/snapshot），录制门控
  snapshot.ts        CS：UI 状态快照（锚点前后；密码框跳过+敏感 label 脱敏）
injected/
  net-hook.js        MAIN world 网络 hook（fetch/XHR 包装；redactBody/redactUrl）
shared/
  types.ts           RawEvent/Snapshot/消息协议（EVENT_MSG 等）
  describe-element   语义描述（aria-label→placeholder→title→关联label→文本）
  input-key.ts       输入框回退链（name→id→placeholder→aria-label）
  redact.ts          敏感脱敏正典（BASE_SENSITIVE_PATTERNS 16 词=10 英文+6 中文
                     label 形态；redactValue + redactNetworkBody/Url）
  assign-session     事件归属会话
  page-id.ts         页面实例标识（跨页事件不丢）
```

**脱敏词表四处副本**（redact.ts 正典 / injected/net-hook.js / server page_snapshot.py /
executor.ts 页内 SENS——CRXJS 原样复制不转译、页内注入不能 import，副本无法消除）：
**修改词表必须四处于同批改齐**，`shared/redact-parity.test.ts` 读四处源码断言词集相等——
漏改即测试红（docs/arch/2026-10-08-redaction-defense-in-depth.md）。

## 采集协议

事件（RawEvent）：`{ sessionId, pageId, seq, ts, kind, payload }`
- `action`：click/submit/input（target=describeElement 语义描述，非 CSS）
- `network`：method/url/status/reqBody/resBody（插件侧首次脱敏；**失败调用也留痕**——
  fetch reject/XHR error/timeout/abort 落 `{status:0,error:…}`，C3 含失败调用）
- `navigation`：page-load
- `snapshot`：锚点前后 UI 状态（forms/labels/tables，结构见 `docs/arch/2026-09-24-ui-snapshot.md`）
- 全部携带的 `url`（含文档 URL location.href）过 `redactNetworkUrl`——SSO 回跳 `?token=` 不落库，
  host/path 保留（系统派生依赖）

上报：CS → EVENT_MSG(runtime) → SW 缓冲 → 批量 POST。**CS 与 SW 不共享 IndexedDB**（经验 #8）；**SW 自发自收不触发 onMessage**（经验 #6，驱动插件须经扩展页面中转）。

## 执行协议（AG 系列，docs/arch/extension-executor-protocol.md）

- 步循环：POST `/executor/skills/{id}/plan` → 逐条 `POST /runs/{id}/step` 交证据换指令 → `finish`
- 交互画像（P1）：plan 携带 `interaction_profile`（YAML 声明→服务端下发），执行器解释——无画像走内置默认
- 脱敏红线（2026-10-07 评审补齐）：snapshot forms 三重防线（password/autocomplete/label）、toasts 敏感整条丢弃、CDP 网络证据 redactNetworkBody/Url——与录制侧同词表（api_key/private_key 等已扩入）

## 开发注意（踩坑速查，详见 docs/references/project-lessons.md）

- 重载插件后必须刷新目标页（孤儿 CS 静默 0 采集，经验 #7）
- **MV3 SW 不热替换**：改插件后须重启常驻浏览器才生效（经验 #16）
- 品牌 Chrome（137+）封禁 `--load-extension`：自动化采集须用 Playwright 自带 chromium
- 自动化采集：`scripts/auto_record.py`（RECORD_CDP_URL 连常驻窗口时录制可见）；raw CDP 录制 `server/scripts/p3_record.py`

## 测试

vitest + jsdom（`*.test.ts` 同目录）共 **99 用例**：describe-element / input-key / redact /
page-id / assign-session / snapshot / capture / capture-redact（文档 URL 脱敏）/ net-hook
（脱敏+失败留痕）/ **redact-parity**（四处词表一致性）/ **executor-injected-regex**
（注入表达式转义扫描——模板串内转义必须双写 `\s`，否则页面收到字面 s）。

**注入页内 JS 纪律**：executor.ts 的 `Runtime.evaluate({expression: \`…\`})` 模板串里，
`\s`/`\n` 会被编译吃掉一层——所有转义一律双写（`\\s`），扫描测试带非空守卫防实现改名后恒绿。
