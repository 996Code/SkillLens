# SkillLens Extension 代码导览

> Chrome MV3 采集插件（Sensor）：只采集，不判断。构建产物 `dist/` 以开发者模式加载。

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
  session.ts         SW：会话管理 + 录制标记（storage.session，CS 经 setAccessLevel 可读）
  uploader.ts        SW：事件缓冲（IndexedDB）+ 批量上报 → http://127.0.0.1:8710/api/v1
content/
  capture.ts         CS：事件采集（action/network/navigation/snapshot），录制门控
  snapshot.ts        CS：UI 状态快照（锚点前后；密码框跳过+敏感 label 脱敏）
injected/
  (网络 hook 注入层)
shared/
  types.ts           RawEvent/Snapshot/消息协议（EVENT_MSG 等）
  describe-element   语义描述（aria-label→placeholder→title→关联label→文本）
  input-key.ts       输入框回退链（name→id→placeholder→aria-label）
  redact.ts          敏感脱敏（SENSITIVE_KEY_RE + redactValue）
  assign-session     事件归属会话
  page-id.ts         页面实例标识（跨页事件不丢）
```

## 采集协议

事件（RawEvent）：`{ sessionId, pageId, seq, ts, kind, payload }`
- `action`：click/submit/input（target=describeElement 语义描述，非 CSS）
- `network`：method/url/status/reqBody/resBody（插件侧首次脱敏）
- `navigation`：page-load
- `snapshot`：锚点前后 UI 状态（forms/labels/tables，结构见 `docs/arch/2026-09-24-ui-snapshot.md`）

上报：CS → EVENT_MSG(runtime) → SW 缓冲 → 批量 POST。**CS 与 SW 不共享 IndexedDB**（经验 #8）；**SW 自发自收不触发 onMessage**（经验 #6，驱动插件须经扩展页面中转）。

## 开发注意（踩坑速查，详见 docs/references/project-lessons.md）

- 重载插件后必须刷新目标页（孤儿 CS 静默 0 采集，经验 #7）
- 品牌 Chrome（137+）封禁 `--load-extension`：自动化采集须用 Playwright 自带 chromium
- 自动化采集：`scripts/auto_record.py`（RECORD_CDP_URL 连常驻窗口时录制可见）

## 测试

vitest + jsdom（`*.test.ts` 同目录）：describe-element/input-key/redact/page-id/assign-session/snapshot 共 24 用例。
