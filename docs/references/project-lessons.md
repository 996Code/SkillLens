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

### 17. dist 重建即废已加载扩展：CS 引用旧 hash 文件名 → 404 静默零采集
- **现象**（S12 T3 实战）：extension `npm run build` 后（未重启浏览器），
  新开页面 CS 全部失效——console 报 `Failed to fetch dynamically imported
  module: chrome-extension://.../capture.ts-<旧hash>.js`（ERR_FILE_NOT_FOUND），
  表现为**静默 0 事件**，SW/popup 一切正常。
- **根因**：构建产物文件名带内容 hash，重建后新文件名替换旧文件；已加载扩展的
  manifest/CS loader 仍引用旧 hash 文件名，而旧文件已被删除。
- **修复**：重启常驻浏览器（同 #16）。
- **预防**：**任何** `npm run build`（哪怕不打算用新功能）之后都要重启常驻浏览器；
  采集健康检查法——录一个已知流程看事件数，或抓目标页 console 找 404。

---

## 六、七系统闭环实战（S43-4，2026-10-01/02）

> 方法论总纲（用户强制，已入 AGENTS.md）：**遇坑先查目标系统官方 harness**
> （容器内一手源码 > Playwright/Healenium 源码 > 搜索文章），结论注明出处。

### 18. 写类按钮"提交成功"是假象：toast 文案不可靠，等写请求落地
- **现象**（ERPNext）：回放点 Save 步骤全 ✓，实体却没建出（服务端校验拒了）。
- **根因**：点击成功 ≠ 提交成功；toast/步骤 ok 都不能证明写发生。
- **修复**（源自 Frappe cypress/support/commands.js 的 intercept+wait 模式）：
  写类按钮点击前记水位，轮询 6s 等新 POST；无新 POST 判"提交被拦"。两步提交
  （Submit→Yes）时 Submit 豁免（plan 全量已知，下一步是确认词）。
- **预防**：任何"提交后验证"以写请求为证据，不以 UI 反馈为证据。

### 19. 模态动画中元素点不上：stability 永不满足 → check(force=True)
- **现象**（ERPNext 列表勾选）：checkbox click 反复超时；等 spinner 消失也无效。
- **根因**：modal 搜索 spinner 是循环动画，Playwright actionability 的 stability
  检查永不满足（元素帧持续变化）；但元素本身可见可点。
- **修复**（源自 Frappe cypress select_listview_row_checkbox——官方就是
  check(force=True)）：force 跳过 actionability 但仍走 CDP 可信输入，框架事件
  层（jQuery 委托）正常收到。
- **预防**：动画元素超时先想 force；**合成 el.click() 不行**（isTrusted=false
  被框架忽略/只翻 DOM 不进框架选中集合，重渲即还原——ERPNext 实测三层降级
  force-check→native-click→force-click 才稳）。

### 20. 空库/空列表不可交互是产品逻辑，不是事件层问题
- **现象**（Odoo）：空库列表行 opacity 0.33+pe:none，Playwright/browser-use/JS
  合成事件全部点不动。
- **根因**：Odoo 空库进入 view sample 模式（演示数据半透明禁交互）——产品行为。
- **修复**（源自 Odoo 自己的 tour 套件：先种数据）：XML-RPC 种一条真实单据后
  列表完全恢复。
- **预防**：目标系统"完全点不动"时先查是否 demo/sample 态，种真实数据。

### 21. 模块激活/初始化必须走 UI toggle，DB 直插不完整
- **现象**（Dolibarr）：DB 手插 llx_const 激活 commande 模块，表单/菜单仍缺失。
- **根因**：模块 toggle 跑完整 init（菜单/权限注册），DB 直插只写配置行。
- **修复**：admin/modules.php?id=25 关掉再开；用户权限补插 llx_user_rights。
- **预防**：所有"改配置生效"类操作优先复刻官方入口（UI/CLI），不直写业务表。

### 22. select2 AJAX 下拉：原生 select 是空壳，必须走 UI 全链
- **现象**（Snipe-IT）：select_option/设值+change/jQuery val 全部无效。
- **根因**：select2 AJAX 渲染层容器与 hidden select 无 DOM/aria 关联，options
  恒空，程序设值不触发 select2 内部状态。
- **修复**：采集侧 select2HostSelect（相邻 hidden select 的 name 进 labels）；
  回放侧 select2 专属策略（点 .select2-container→填 .select2-search__field→
  点 .select2-results__option）。弹层挂 body 锚定法：打开时原容器带 --open 类
  且前邻即 hidden select。
- **预防**：自绘控件（select2/picker）一律走"开容器→搜→点结果"UI 链，永不
  直填 hidden input（破坏组件状态）。

### 23. 跨 frame 定位：图标操作与顶层菜单纯文本同名会抢先命中
- **现象**（禅道）：iframe 业务页 a[title=执行] 与顶层菜单"执行"同名，主 frame
  text 策略先命中菜单项，点错元素。
- **根因**：locate 全策略链按 frame 顺序+策略优先级遍历，无 [title=] 优先。
- **修复**：两级遍历——第一轮全 frame 只找可见 [title=]（图标操作语义最强），
  第二轮原全策略链。
- **预防**：iframe 系统（禅道类）图标按钮优先属性锚（title/aria-label）。

### 24. 无属性输入框的变量化：表单组 label 终极回退
- **现象**（JeecG 设计器）：抽屉 input 无 name/id/placeholder，inputKey 三回退
  全空，学习后无法换参。
- **修复**：inputKey 回退链末尾加 formGroupLabelKey（.cgf-item/.ant-form-item/
  .form-group 内 label 文本，如"*表名"）——变量化从 0 到 2，Create 换参全 PASS。
- **预防**：低代码设计器类页面输入框常无属性，采集层必须有表单组语义锚。

### 25. 初始密码/安全策略弹窗锁死页面：超时=有交互没识别到
- **现象**（若依）：初始密码登录成功后页面锁死，任何定位超时。
- **根因**：强制"安全提示"弹窗（您的密码还是初始密码）没点确定，overlay 挡全页。
- **修复**：_confirm_logout_box 类通用处理（.el-message-box__btns button 全局
  类 filter 确定，轮询）。
- **预防**（用户 Debug 铁律）："只要是超时，那肯定是有交互你没识别到"——先截图
  查弹窗/提示/开态，不空等加超时。

### 26. 中文行文本做行锚：无空格 split 失败，按 ASCII 词边界切
- **现象**（若依/JeecG）：宿主行文本"SL-演示订单 20261001…"做行过滤，split()[0]
  拿到整串必败。
- **修复**：`re.findall(r"[A-Za-z0-9_]{4,}", row_text)` 取首 token；且行文本
  需含 ASCII alnum 特征门（排除"未选中任何数据"空表文案误入）。
- **预防**：中文混排行取锚词用词界 regex，不用 split。

### 27. el-select 空下拉是裸 span 容器，不是 input 属性
- **现象**（若依）：element-plus el-select 空态渲染为 .el-select__placeholder
  容器裸 span 文本，placeholder 属性策略不命中。
- **修复**：locate 加 el-select-placeholder 专属策略（:has(.el-select__placeholder)
  filter has_text）。
- **预防**：element-plus 组件的"属性"常渲染在容器层，先看渲染 DOM 再定策略。

### 28. Windows subprocess 中文输出：默认 GBK 崩读线程
- **现象**：编排脚本跑 docker exec 输出中文，subprocess text=True 直接崩。
- **修复**：encoding="utf-8", errors="replace"。
- **预防**：所有 subprocess 调用统一带此参数（test_export 曾因此回归）。

### 29. 链式回放的行锚陈旧：override 值须注入行过滤（S43-5）
- **现象**（JeecG Sync/Fill）：Create PASS 但 Sync/Fill 换参回放行过滤不到
  新表行——行点击步 labels 是录制时宿主行文本（旧表名），跨轮必然陈旧。
- **修复**：execute_plan 增加 row_anchor_hints——_execute_skill 把 overrides
  值列表传入，click/checkbox 行锚提取优先级最前（>6 字符且含 ASCII alnum
  门与既有信号一致）。编排脚本换参时同步传 {"*表名": form}。
- **预防**：凡"步骤锚定在动态实体行上"的技能（列表行操作类），换参必须
  把新实体名同时作为行锚提示注入；无输入变量的技能靠这条通道换参。
  同哲学：断言期望值是纯数字≥12/hex≥16 的实体 id 时跨轮必漂移，记录
  不判定（assert_eval._DYNAMIC_EXPECT）——回放命中行≠录制行不是回归。

### 30. chrome.debugger 桥接回放（AG0 spike 实证，2026-10-03）
- **结论**：插件内回放技术路径全通——attach / CDP `Input.dispatchMouseEvent`
  可信点击（isTrusted=true，页面状态更新）/ `Network.getResponseBody` 取响应体
  / detach 四件事 PASS；MV3 SW 在 debugger 事件驱动期间 30s 观察窗不被杀；
  attach 冲突有明确错误形态（"Another debugger is already attached"）可转
  用户提示（关 DevTools 重试）。
- **关键时序**：Network listener 必须在触发动作**之前**注册——响应早于注册
  即丢事件（spike 首跑 body=null 的根因）。AG3 步循环遵循"先订阅后动作"。
- **出处**：与 Playwright 同源 CDP（Input/Network/Runtime 域），等价于把
  服务端执行通道搬进插件；对照 Selenium IDE 的 content script 合成事件
  （isTrusted=false 被框架忽略，lesson #19）正是分水岭。
- 证据：spike/ag0_drive.py 复跑输出（4/4+保活+冲突形态）。

### 31. 声明式清单不塞复杂 shell——引号嵌套是深渊（AF2 实证）
- **现象**（禅道探针）：manifest YAML 里的 shell 含密码抽取（grep+正则+多层
  引号），单引号双写/块标量折叠/`\K` 转义三层地狱，三种写法全断——sh 报
  "Unterminated quoted string"。
- **修复**：复杂 shell 放独立脚本 `adapters/scripts/zentao_db.sh`（密码从
  容器内应用配置抽取，不落清单），manifest 只写 `sh /opt/skilllens/x.sh
  "<SQL>"`；探针运行时 `_ensure_helper_scripts` 自动 docker cp 注入。
- **预防**：manifest 是声明物不是脚本容器——凡引号超两层/含正则反斜杠的
  shell 一律外置脚本（设计原则①的 escape hatch）。YAML 里 shell 用单引号
  标量+双写转义仅适用于简单命令。
- 禅道容器 root 密码不在 env（官方镜像存 /apps/zentao/config/my.php）——
  MYSQL_ROOT_PASSWORD 假设不通用，逐容器核实凭据形态。

### 32. persistent_context 常驻浏览器 + 外部 connect_over_cdp 的驱动冲突（AF3 实证）
- **现象**：live_browser.py 宿主（launch_persistent_context）开着时，外部脚本
  connect_over_cdp 后 `ctx.new_page()` 报 "Connection closed while reading
  from the driver"；且宿主异常退出会污染 CDP 状态（后续连接全断）。
- **根因**：两个 Playwright driver（宿主 + 外接）对同一浏览器并发操作，
  newPage 通道冲突；宿主崩后 socket 半开。
- **修复**：外部脚本**复用既有页**（ctx.pages[0]）不 new_page；宿主挂了先
  TaskStop/重启 live_browser（profile 在 /tmp/skilllens-live-profile，登录态
  不丢）再连。
- **预防**：编排脚本连 9222 一律复用 pages[0]；需要多页时开自己的
  launch_persistent_context 或直连 CDP HTTP 接口，不经 Playwright ctx。

### 33. Odoo 17 改密：SQL 直写 passlib 串，生成必须用 passlib 权威函数（AF3 补验实证）
- **现象**：本地容器超管密码遗失需重置。odoo shell `write({"password":...})`
  打印成功但登录仍拒（Odoo 17 密码字段 write 不触发 crypt 管线落库）；
  手搓 pbkdf2 串（hex salt 三段式）也不被识别。
- **修复**：`passlib.hash.pbkdf2_sha512.using(rounds=600000).hash(pw)` 生成
  （注意 `--with passlib` 的安装日志会混进重定向 stdout——分离 stderr 或
  python -c 写文件），SQL 直写 res_users.password，XML-RPC authenticate 验证。
- **预防**：成熟项目对照的极端案例——哈希串格式没有"差不多"，必须用目标
  系统同源库生成（passlib 之于 Odoo，如同官方 harness 之于回放）。禅道
  反例：md5 直写即可（无盐无 crypt 管线）——逐系统核实密码栈再动手。

---

*更新记录：2026-09-24 初版（Sprint 0-4 + Sprint 4.5 全自动闭环的踩坑汇总）；
2026-09-24 二版（Windows 移植清单 + 回放水合竞态，§五）；
2026-10-02 三版（§六 S43-4 七系统闭环实战 11 条：#18-#28）；
2026-10-02 四版（#29 链式回放行锚陈旧——JeecG Sync/Fill 收尾）；
2026-10-03 五版（#30 chrome.debugger 桥接回放 AG0 spike 实证）；
2026-10-03 六版（#31 声明式清单不塞复杂 shell——AF2 禅道探针实证）；
2026-10-03 七版（#32 persistent_context 双驱动冲突——AF3 登录验证实证）；
2026-10-03 八版（#33 Odoo 17 密码栈——passlib 权威生成实证）。*
