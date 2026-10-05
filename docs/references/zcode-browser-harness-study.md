# zcode harness 浏览器层全链学习（一手源码精读）

> 来源：/d/github/zcode-src/packages/desktop/src/main/browserView/ 全量 11 文件精读。
> 用途：SkillLens executor.ts 对照基线。每个模式须真机实证后才移植。

## 五层架构总览

```
L1 语义识别  SNAPSHOT_SCRIPT（browserCommandScripts.ts）
L2 ARIA 识别 browserPlaywrightDomSnapshot.ts（Playwright injectedScript）
L3 定位执行  browserPlaywrightLocatorExecutor.ts（actionProbe 探针）
L4 交互原语  browserCommandInput.ts + browserVirtualClipboard*.ts
L5 页面控制  browserCommandPageHandlers.ts + browserCommandState.ts
```

## L1 语义识别（SNAPSHOT_SCRIPT）

- ACTION_SEL = `a[href], button, input, textarea, select, [role], [onclick], [tabindex], summary, label, [contenteditable]`——可交互语义元素
- DOM_SEL 独立限额（正文语义节点与动作元素分开，防挤占）
- isHidden：`display:none || visibility:hidden || opacity:0 || 0尺寸` 四重检查
- accName 优先级：`aria-label > alt > title > placeholder > innerText`
- implicitRole 推断（a[href]=link、button=button、input 按 type…）
- ref 系统：`window.__zcodeRefs = Map<ref, Element>`——识别一次、后续动作按 ref 引用（避免重复文本匹配漂移）
- buildSelector：#id 优先，否则 nth-of-type 链（深度≤6）
- parentRef：WeakMap 反查最近被选祖先（层级线索）

## L2 ARIA 识别（domSnapshot）

- isolated world（`Page.createIsolatedWorld` worldName="zcode-playwright-dom-snapshot"）注入**完整 Playwright injectedScript**（从 playwright-core 固定版本读字符串字面量，66 行 loader）
- `incrementalAriaSnapshot(root, {mode:"ai"})` 生成带 ref 的 ARIA 树
- iframe 递归：aria-ref → DOM.describeNode 取 frameId → OOPIF 时 `Target.attachToTarget` + 重建 context（含 OOPIF 导航竞态刷新 Target.getTargets 重试）
- 预算纪律：顶层 3s；iframe 总预算 1s/子 500ms
- 归一化：去内部 ref/cursor、压平无语义容器（generic/listitem/group）、删无名 img

## L3 定位执行（locatorExecutor 核心）

**actionProbe 探针**（动作前置门槛，页面内 async 表达式）：
1. `querySelectorStrictWithVisibleFallback`（严格选择器+可见回退）
2. elementState 检查：visible / enabled / editable（按 op 需要）
3. `scrollIntoView` + **滚动对齐轮换**：center→end→start→nearest（pointerAttempt % 4——单一对齐被 sticky header 挡时下次换位）
4. **稳定双帧**：连续 2 个 rAF 内 rect 不变才认为稳定（≤10 帧窗口）；el-table 换 node 竞态处理——detach 后**重新解析 locator** 再比几何
5. **hit-target 校验**：中心点 `elementsFromPoint` 逐 shadow root 层命中比对——**被遮挡直接判 covered 不点**（含 obstruction 描述）
6. 输出 `{count, actionable, x, y, checked, reason, obstruction}`

**重试循环**：POLL 50ms；默认 3s 短预算（教训注释：旧 30s 导致猜错 locator 后长时间无效轮询）；document race 恢复（resetDocumentContexts 重解析）。

**超时错误消息带行动指引**："Do not retry the same locator. Take a fresh domSnapshot(), rebuild from snapshot-proven facts"——错误即导航。

## L4 交互原语

**click（trusted 三事件）**：`Input.dispatchMouseEvent` mouseMoved→mousePressed→mouseReleased（clickCount、button、modifiers 位掩码）。**zcode 全部 click 都走这个**，不用 JS .click()（除 check 的状态切换也是 trusted click）。

**fill 两级**：
1. 快速路径 `injected.fill`（Playwright DOM 层：native setter+input/change 事件）；color/date/range 等 set-value 型直接设值返回 done；文本型 `selectText` 后返回 **"needsinput"**
2. needsinput → `focusForInput`（retarget follow-label → focusNode → **inputTargetToken** defineProperty 到元素上）→ `pasteTextIntoFocusedTarget`
3. 虚拟剪贴板粘贴：构造 `DataTransfer` + 派发 `ClipboardEvent("paste")`（bubbles/cancelable/composed）；页面 preventDefault 时 fallback：input/textarea 用 `setRangeText`+InputEvent；contenteditable 用 `execCommand("insertText"|"insertHTML")`
4. **焦点防漂移**：`assertFocusedInputTarget`——deepestActiveElement（**shadow DOM+iframe 双穿透**）上的 token 与预期比对，不匹配即抛错

**press**：KEY_MAP 完整映射（key/code/windowsVirtualKeyCode）；组合键顺序：held down → last down → last up → held 逆序 up。

**scroll**：`mouseWheel`（实证教训：synthesizeScrollGesture 在 Electron 41/Chromium 146 webview 静默成功但无 wheel 事件）。

**drag**：mousePressed → 10 插值 mouseMoved（buttons:1 按住位）→ mouseReleased。

**select**：JS 层 option.value 精确→可见文本匹配，dispatch input+change。

**setChecked**：状态需变时 trusted click，**事后读回验证**（did not change 即抛错）。

## L5 页面控制

- **navigate**：URL 白名单（http/https/about:blank）；settleNavigation=Promise.race(load/10s timeout/abort)；**ERR_ABORTED 容错**：SPA 重定向会让 loadURL reject 但新 document 已提交——用 `confirmAbortedNavigationCommitted`（URL 等价归一 host/path/search + readyState interactive/complete + href 一致）确认成功而非误报失败
- **waitForURL**：poll URL → waitForDocumentState；**明确不支持 networkidle**
- **waitForDocumentState**：readyState 判定（load=complete / domcontentloaded=非 loading）
- **evaluate**：awaitPromise + timeout + abort 时 `Runtime.terminateExecution`
- **dialog**：`Page.handleJavaScriptDialog`
- **screenshot**：CSS 像素校正（Page.getLayoutMetrics cssVisualViewport，Retina legacy metrics 2 倍坑）；clip/fullPage 用 scale:1
- **副作用分类**：isSideEffecting 白名单（导航/click/fill/type/press/scroll/hover/select/check/drag/dialog/evaluate…）

## 与 SkillLens executor.ts 的差距表

| # | zcode 模式 | 我们现状 | 影响 |
|---|---|---|---|
| 1 | ref 系统：识别→挂 Map→动作按 ref | 每步 label 文本重新匹配 | 多命中/页面变化漂移 |
| 2 | actionProbe：visible/enabled/稳定双帧/hit-target 前置 | 直接查 rect 就点 | 点被遮挡/未稳定元素假 ok |
| 3 | trusted 三事件 click 为主 | JS elClick 优先（实证时序敏感） | hydration 未完成时假 ok |
| 4 | 动作后效果验证（setChecked 读回） | click 后只 sleep | 假 pass（#269 根因层） |
| 5 | fill 两级+inputTargetToken+粘贴事件 | focus+execCommand+focus 验证 | 焦点漂移时写错元素 |
| 6 | 滚动对齐轮换 | 单一 scrollIntoView | sticky header 挡点击 |
| 7 | 3s 短预算快失败+错误带行动指引 | 长重试循环 | 卡死循环（fill 10s×N） |
| 8 | ERR_ABORTED 导航容错 | 无 | SPA 重定向误报 |
| 9 | iframe/OOPIF attach+isolated world | getFrameTree+createIsolatedWorld（已有近似） | — |
| 10 | deepestActiveElement shadow+iframe 穿透 | 单层 activeElement | shadow 内焦点丢验证 |

## 移植优先级（对应在修 bug）

P0（#269 直接相关）：#2 actionProbe + #3 trusted click + #4 效果验证
P1：#5 fill 加固、#7 预算纪律
P2：#1 ref 系统（大改，需主计划立项）、#6 #8 #10
