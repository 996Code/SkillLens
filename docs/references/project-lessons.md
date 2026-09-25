# 项目经验库：E2E 实战踩坑与修复模式

按 Sprint 累积的实战经验。每条含：现象 → 根因 → 修复 → 预防。新 Sprint 计划与 E2E
验收前先过一遍本清单（防跑偏检查清单 §12 的补充材料）。

---

## 一、浏览器自动化（Playwright）

### 1. page.on("response") 的 async 回调可能静默不触发
- **现象**（Sprint 4 T5）：回放执行 3 步全 ✓、保存真实生效，但 observed 网络观察
  恒为空 → 断言全部误判 fail。
- **根因**：Playwright 的 `on()` 对 async 回调支持与版本相关，可能静默不调用。
- **修复**（d9318d0）：同步壳回调 + `asyncio.get_running_loop().create_task(collect())`。
- **预防**：诊断方法——同页面用同步 lambda 计数 response 事件，若同步能收到而 async
  收不到，即此问题。

### 2. 固定收尾等待会漏掉链式请求
- **现象**（Sprint 4 T5）：saveFormConfig（同步响应）观察到了，但保存后的
  getTableConfigByFormConfigId / saveTableConfig 链式请求 observed=null。
- **根因**：点击"保存"后的链式请求晚于固定 1.5s 收尾窗口。
- **修复**（6a4befa）：收尾等待改为断言模板驱动——轮询 observed 直到所有
  api_template 命中或超时 10s，全命中即止；无目标模板时退回 1.5s。
- **预防**：凡是"操作后断言网络"，等待条件用"预期的东西到了没有"，不用固定秒数
  （同"别让用户等固定秒数"的即时反馈原则）。

### 3. SPA goto 后立即操作 → 空白页
- **现象**（Sprint 4 T5）：goto 返回后截图 27KB 空白，定位失败。
- **修复**（c216b1e）：`wait_for_load_state("domcontentloaded", timeout=15000)` +
  固定 2s 渲染余量（njmind SPA 实测需要）。
- **预防**：SPA 目标一律 domcontentloaded + 余量，不要信 load 事件。

### 4. persistent_context 异常退出会锁死 profile
- **现象**（Sprint 4.5）：脚本异常退出未关浏览器，下次 launch 超时 180s。
- **根因**：Chrome SingletonLock 残留。
- **修复**：脚本 try/finally 里 `ctx.close()` + `pkill -f <profile>` 兜底。
- **预防**：带 profile 的脚本必须 finally 清理。

### 5. MV3 插件测试必须 headed 模式
- `launch_persistent_context` + `--load-extension` 在旧 headless 下不加载扩展；
  用 `headless=False`（新 headless 需 Playwright 较新版本支持，实测用 headed 稳）。

## 二、扩展（MV3）机制

### 6. SW 自发自收不触发 onMessage
- **现象**（Sprint 4.5）：从 SW 页面 `chrome.runtime.sendMessage` 给自己发
  START_RECORDING，返回 None，server 上 session 根本没创建。
- **根因**：runtime 消息不会回环到同上下文的 onMessage 监听器。
- **修复**（auto_record.py）：从扩展自身页面（popup.html 同源上下文）中转发消息：
  `page.goto(chrome-extension://{id}/popup.html)` 后 evaluate sendMessage。
- **预防**：驱动插件内部控制开关，一律经扩展页面上下文中转。

### 7. 孤儿 content script：重载插件后必须刷新页面
- **现象**（Sprint 1）：重载插件后旧页面的 CS 报
  `Extension context invalidated` 且静默 0 采集。
- **根因**：旧 CS 属于已卸载的扩展实例。
- **预防**：改插件代码后，所有目标页面都要刷新；控制台这类报错在重载瞬间属预期。

### 8. MV3 各上下文不共享存储
- CS 与 SW 不共享 IndexedDB（事件流必须 CS → runtime 消息 → SW）；
  `storage.session` 默认仅扩展页可读，要 `setAccessLevel(
  "TRUSTED_AND_UNTRUSTED_CONTEXTS")` 后 CS 才能读录制标记。

## 三、njmind 目标系统特性

### 9. 登录与状态码约定
- 内网验证码留空可直接登录（admin 账号实测）；登录后 token 在 cookie。
- 业务状态码在响应顶层 `code` 字段（非 HTTP status，也非 data.code）——
  STATE_KEY 正则已按此适配。
- 表单设计器 saveFormConfig reqBody 约 100KB 且**字段默认值不在其中**
  （UI 快照需求的直接依据，Sprint 5 议题）。

### 10. 表单页多个"请输入"
- 表单设计器页有 5 个 placeholder="请输入" 的输入框，语义定位必须
  `.first`（表单名框），或结合 disabled 属性排除 code 框。

## 四、计划/流程经验（SDD 执行）

### 11. brief 代码与自身测试矛盾 → "测试即规格"最小修正
- 累计 5 处（window_signature 尾管道符、path_matches 正则版、field_change 全等
  语义等）：brief 里的实现代码与其测试用例自相矛盾时，以测试为准最小修正实现，
  审查者独立 trace 确认。已固化为既定处理模式。

### 12. 单测通过 ≠ 真实可用，E2E 修复轮必须预留
- 每个浏览器/插件相关 Sprint 都出现单测全绿但真机首跑失败（Sprint 0/1/4 各 3-6 处）。
- Sprint 计划里 T-final 必须是真实环境验收，且预留 1-2 轮修复时间。
- 全自动闭环（scripts/auto_record.py + njmind_login.py）落地后，E2E 不再依赖
  用户手动操作 njmind。

### 13. 迁移噪音：autogenerate 反复报 raw_event 假 NOT NULL
- 已第 3 次出现（Sprint 4 T1 又遇）。Sprint 5 待办：做一次对账迁移根治。

## 五、Windows 移植与回放可靠性（2026-09-24）

### 14. Windows 环境移植清单（macOS → Win11 实测）
- **Node 版本**：系统 Node 22.10 不满足 vite 8 要求（≥22.12）；用便携版 Node 24
  前缀 PATH 解决（放在仓库外 D:\github\.tools）。
- **vite 8.3.0 Windows 回归**：config 加载时 rolldown `sourcemapPathTransform` 收到
  Array → `path.resolve` 抛错，build/vitest 全挂；降 `~8.2.2` 后正常（已 pin 进
  package.json）。
- **npm 可选依赖 bug（npm/cli#4828）**：lockfile 缺 win32 原生绑定条目，`npm ci`
  后仍缺——`npm i @rolldown/binding-win32-x64-msvc --no-save` 补装。
- **Playwright 浏览器下载**：官方 CDN 国内不通，`PLAYWRIGHT_DOWNLOAD_HOST=
  https://cdn.npmmirror.com/binaries/playwright` 镜像可解。
- **脚本可移植性**：`pkill` 不存在（auto_record 的 finally 会吞掉落库验证段，
  已加 shutil.which 守卫）；`/tmp` 在原生 Python 下解析为盘符根（D:\tmp）。
- **品牌 Chrome（137+）封禁 `--load-extension`**：channel="chrome" 时插件被静默
  拒载、SW 找不到——采集（需插件）必须用 playwright 自带 chromium；回放不需
  插件，可用真 Chrome。
- **uv 镜像重写 lock**：本机 uv 配置阿里云镜像会重写 uv.lock 的 URL（版本/哈希
  不变），提交前 `git checkout -- server/uv.lock` 还原。

### 15. 回放 fill 水合竞态：值被 SPA 回写 → 脏检查跳过保存 → observed 全空
- **现象**（Windows 复现 2 次）：回放步骤全 ok，但 4 断言全 `observed_status=null`
  且表单名未变——njmind 水合晚于 fill 把输入框改回旧值，保存的脏检查认为无变化
  不发请求，网络观察自然为空（表象与经验 #1 相同，根因不同）。
- **修复**：runner `execute_plan` 的 input 分支 fill 后轮询确认 `input_value ==
  value`，被回写则重填（3 次上限）；确定性测试
  `test_execute_plan_input_survives_hydration_overwrite`（JS 首次 input 事件改回
  旧值）。
- **预防**：回放"输入"步骤一律确认写入生效再点击保存；observed 为空时先分清
  是"回调没收到"（#1）还是"请求根本没发"（本条，查表单值是否变化）。

### 16. MV3 SW 不热替换：dist 重建后运行中的 SW 仍是旧代码
- **现象**（S10 T5 实战）：source 标记功能代码已构建进 dist，但常驻浏览器里
  SW 行为依旧是旧版（显式传 real_traffic 仍落 demo）；`chrome.runtime.reload()`
  后 SW 进入不可唤醒状态（任何页面活动都不再激活）。
- **根因**：MV3 SW 实例在浏览器会话内不随磁盘文件更新；runtime.reload 对
  unpacked 扩展在此场景下导致 SW 挂死。
- **修复**：重启整个浏览器（profile 保留，登录态不丢）。
- **预防**：改插件代码后要让它生效，一律"重 build → 重启常驻浏览器"，不要指望
  热替换；诊断法——通过 CDP 在 SW 上下文 fetch 自身资产检查关键字符串是否在。

---

*更新记录：2026-09-24 初版（Sprint 0-4 + Sprint 4.5 全自动闭环的踩坑汇总）；
2026-09-24 二版（Windows 移植清单 + 回放水合竞态，§五）。*
