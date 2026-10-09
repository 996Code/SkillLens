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

### 34. 扩展执行器三层坑（AG3 十轮排障实录，2026-10-03）
- **坑 1（最隐蔽）SQLAlchemy JSON 别名**：executor_step 变异 `plan["executor_state"]`
  内嵌 dict 再 `{**plan}` 赋回——新旧值是同一对象判等，UPDATE 根本不发；
  响应正常（内存态）+同 session 读"看似推进"，只有**新连接 raw 读**才现形。
  修复=deepcopy 后变异；回归测试必须新 session 重读。
- **坑 2 MV3 消息面**：①多 listener 的 sendResponse 竞争互踩（undefined 响应）
  →单一 listener 分发；②`return false`+同步 sendResponse 丢 channel；
  ③SW 里挂长任务的 sendResponse channel 被 SW 空闲终止。终局=长任务不进
  消息层，独立页面直调模块函数。
- **坑 3 popup 生命周期**：执行中导航别的 tab → popup 被 Chrome 冻结/关闭，
  整个执行链静默死（run 卡 running 无错误）。终局架构=执行住独立
  executor.html tab（全程可见也顺带满足产品要求）。
- **坑 3.5 CRXJS**：只转译 manifest 功能入口引用的 html——新页面须经
  options_ui/action 等引用进构建，web_accessible_resources 原样复制不转译。
- **预防**：扩展新页面先查 manifest 引用链；JSON 列更新一律 deepcopy；
  SW 长任务一律换页面承载。

---- **现象**：本地容器超管密码遗失需重置。odoo shell `write({"password":...})`
  打印成功但登录仍拒（Odoo 17 密码字段 write 不触发 crypt 管线落库）；
  手搓 pbkdf2 串（hex salt 三段式）也不被识别。
- **修复**：`passlib.hash.pbkdf2_sha512.using(rounds=600000).hash(pw)` 生成
  （注意 `--with passlib` 的安装日志会混进重定向 stdout——分离 stderr 或
  python -c 写文件），SQL 直写 res_users.password，XML-RPC authenticate 验证。
- **预防**：成熟项目对照的极端案例——哈希串格式没有"差不多"，必须用目标
  系统同源库生成（passlib 之于 Odoo，如同官方 harness 之于回放）。禅道
  反例：md5 直写即可（无盐无 crypt 管线）——逐系统核实密码栈再动手。

### 35. 动作成功≠效果成功——交互原语要"探针准入+效果验证"（zcode 学习落地，2026-10-05）
- **现象**：JeecG #269 插件端十余轮死循环——click 报 ok 但 modal 没开、
  fill 报 ok（value_after 有值）但值写进了列表页搜索框、保存 ok 但 addAll
  请求从未发出。每层都"成功"，链路整体全错。
- **根因群**（六条独立但叠加）：①hydration 窗口（按钮 DOM 在、React
  onClick 未绑）直点约 1/5 假 ok；②resolver miss 重试轮里的 Page.reload
  摧毁已开的 modal；③fill form-item 匹配多命中时文档序在前的是列表页
  查询栏（modal 挂 body 尾部）；④`!!querySelector('.ant-modal-content')`
  是假信号——ant 关闭后残留 0×0 隐藏 wrapper，判定必须带 rect.width>0；
  ⑤聚焦豁免分支 return 不落库 cursor，下一条 fill 上报被幂等判 duplicate
  领回聚焦步成死循环；⑥LLM 网关配额错误串（HTTP 200 content 形态）被
  当 locate_repair 提案注入。
- **修复**（=zcode browserPlaywrightLocatorExecutor 模式逐条真机实证后
  移植）：actionProbe 探针准入（visible+稳定双帧 rAF+elementsFromPoint
  hit-target）；click 双通道（elClick 首选/trusted 坐标兜底）+modal 效果
  读回验证；resolver 禁 reload（goto 后首轮除外）；fill modal 内优先+
  name/id 级+iframe 兜底（createIsolatedWorld）；豁免分支补持久化；
  配额错误串防线（Token额度/quota 关键词弃用提案）。
- **预防**：写一个交互原语必须配一个"效果读回"；多层重试里的副作用
  （reload）先问会不会摧毁上游成果；querySelector 存在性≠可见性。
  网关 200 的错误串也是错误——提案注入前过基础设施错误词筛。

### 36. env fallback 写死内网地址=红线违例（全量评审实锤，2026-10-07）

- **现象**：`cfg.get("NJMIND_LOGIN_URL") or "http://192.168.99.22/..."`——
  env 优先看似合规，但 fallback 字面量把内网网关拓扑固化进 8 个已提交
  文件（7 脚本+dev_executor.py）。
- **修复**：fallback 一律改"缺失即 sys.exit 报错"——宁可不跑，不把
  地址写进库。`git grep 192.168` 收尾自扫纳入提交前检查。
- **预防**：env 变量的 fallback 永远不是放置敏感值的合法位置；"网关
  域名不提交"红线扫描要含 IP 字面量，不止域名。

### 37. 验收路径=声明路径≠真实路径（P2.5 插件配对 401 实锤，2026-10-07）

- **现象**：P2.5 URL 配对"7/7 通过"——验收走的是服务端带 token 的
  GET /adapters/match 路径；插件开录路径 session.ts 裸 fetch 无 Bearer，
  挂鉴权守卫的端点必 401，catch 静默回退 njmind。功能在真实用户路径
  从未生效。
- **修复**：插件侧复用 getToken() 带 Bearer+5s 超时；server 补 401 守卫
  测试钉死语义（防未来有人"顺手"给该端点摘鉴权）。
- **预防**：每条功能验收问一句"用户真实触发的代码路径是什么"——
  服务端脚本直调 API 验收 ≠ 插件/popup/页面真实链路验收。try/catch
  吞错的"回退默认"分支会掩盖整条功能失效，回退必须留痕（console/log）。

### 38. 模型加列漏写迁移：create_all 测试恒绿而全新部署必崩（三轮评审实锤，2026-10-08）

- **现象**：`Skill.system` 列在模型里、36 支迁移无一建它——`alembic upgrade head`
  出来的生产库上任何 skill 查询 `no such column` 崩；而测试因 conftest 用
  `create_all` 建库（按当前模型直接建）永远绿。
- **根因**：测试建库与生产建库是**两条路径**，偏差无人看守；且该列本身是从不写入的
  死列（真实系统派生走 system.py 的 host 映射）。
- **修复**：删死列（比补迁移干净）；新增 `test_schema_drift.py`——真实跑
  `alembic upgrade head` 到临时库，对比 metadata 的**列与索引**（双向）。
- **预防**：模型动列/动索引必须同批写迁移，验收标准是 drift 测试绿，不是"测试能跑"。

### 39. 结构测试必须自带非空守卫（否则实现改名后静默恒绿，2026-10-08）

- **现象**：源码扫描类测试（如"注入表达式零单反斜杠转义"）在实现重构、
  `expression:` 改名后匹配数归零——断言"没有坏模式"对空集恒真，测试变
  vacuous pass，防线无声消失。
- **修复**：扫描测试同时断言**锚点存在**：`expression: \`` 出现次数 ≥10、
  且含已知字面量（`label.replace(/[*\\s]/g, '')`）——实现改名/搬走即红。
- **预防**：任何"断言没有 X"的测试，都配一条"断言样本中有 Y"的非空守卫。

### 40. 注入页内 JS 的模板串转义会少一层（fill 剥掉字母 s 实锤，2026-10-08）

- **现象**：resolver 兜底 fill 的 label 归一化对含 s 的英文标签必失败——
  写在反引号里的 `/[*\s]/g` 被 TS 编译成页面的 `/[*s]/g`，label 里每个字母 s
  被剥掉（"Sales"→"Sale"）。主拷贝写的是 `/[*\\s]/g` 所以只有兜底拷贝坏。
- **根因**：模板字面量里 `\s`、`'\n'` 会被烹饪一层；注入表达式里的转义必须双写。
- **修复**：三处改双写 + 扫描测试（带§39 非空守卫）钉死；dist 产物 grep 复核。
- **预防**：review 注入代码时专门看转义层数；"双拷贝"型代码（同一段逻辑两份）
  出现行为分叉的第一嫌疑就是转义/字面量差异。

### 41. 同一安全词表的多份物理副本必须配跨文件一致性测试（2026-10-08）

- **现象**：脱敏词表四处副本（TS 正典 / MAIN-world 纯 JS / 服务端 Python / 页内注入
  JS）各自演化——net-hook 只有 6 词、正典 10 词，注释都自称"同源"；录制路径
  `?api_key=` 明文落库进 LLM prompt。四份还全缺中文 label 形态。
- **根因**：CRXJS 对 `injected/*.js` 原样复制不做 TS 转换、页内注入不能 import——
  副本**技术上无法消除**，"保持同步"只能靠纪律，纪律必漂移。
- **修复**：四份统一 16 词 + `redact-parity.test.ts` 读四处**源码文本**断言词集相等
  （正则/引号列表双解析器）——漂移在 CI 失败。
- **预防**：识别"不得不复制的知识"（词表/判定逻辑/协议常量），一律配一致性测试或
  生成式单一来源（对照 export_shared.py 的逐字内嵌方案）。

### 42. 脱敏回显必须配掩码回填，否则保存即销毁凭据（2026-10-08）

- **现象**：GET yaml 打码 `***` 防凭据回显——但 web 编辑器是"GET 回显→改两行→PUT
  原文"，`***` 被写回磁盘，演示容器凭据一次保存即丢。安全修复本身成了数据破坏。
- **根因**：打码只考虑了"读"路径，没走一遍"读-改-写"全路径复核。
- **修复**：`restore_masked_secrets()` 保存时对仍是掩码的敏感键按行级 FIFO 回填磁盘
  旧值（保留注释；显式改写优先）。
- **预防**：任何上掩码/转换的回显，验收必须含"原样保存一轮，数据无损"的往返测试；
  子代理的安全修复必须按真实调用路径复核，不能只信其报告。

### 43. conftest 硬编码 ./test.db：并行跑两套 pytest 会互撞（2026-10-08 实测）

- **现象**：全量 pytest 跑到中段成片 `no such table: user`（36 errors），另一套
  定向 pytest 同时在跑——共用 `sqlite:///./test.db`，A 套 conftest drop/recreate 时
  B 套正在读。
- **根因**：conftest 固定库名，无进程隔离。
- **修复**（当下）：全量与定向互斥——跑全量前确认无其它 pytest 进程
  （`Get-CimInstance Win32_Process` 查命令行）。
- **预防**（待办）：conftest 改每进程独立库（如 `test-{os.getpid()}.db`）；
  子代理并行修复期间绝不让它们各自跑 pytest。

### 44. "测试恒绿但生产必错"的三种高发形态（三轮评审方法论，2026-10-08）

- **形态一：替身过简掩盖前提**。写水位判定 `len(observed) > mark` 在替身页（零 GET
  响应）下正确，真实页面（加载即有 GET 噪声）下被拦提交误放行成 pass——测试
  恰好缺"点击前已有 GET 响应"这个前提。修法：为每个判定分支问"真实页面上
  这个前提一定成立吗"，把前提写成用例。
- **形态二：注释语义 ≠ 实现语义**。`runner.py:332` 注释"归一化由编译侧保证"而
  编译侧插的是原始 URL。修法：评审时把注释当断言逐条对照实现。
- **形态三：副本漂移**。见 #41/#40。修法：一致性测试或单一来源。
- **通用**：三轮 5 个 🔴 里 4 个属这三类——**跑测试发现不了，逐文件读代码才能**；
  全量评审的价值正在于此。

### 45. 修复"激活从未验证过的路径"要单独成批（插件三缓修的决策依据，2026-10-08）

- **现象**：三个确证缺陷（firstLocateAfterGoto off-by-one、Get Items 二拷贝缺
  CSRF 头、hover-trigger 假报 clicked:true）"修好"的直接效果是**激活一条从未被
  真机验证过的路径**（reload 自愈 / Frappe 直调 API / 菜单挂载校验），可能翻转
  现有 52 链矩阵的通过率——而那可能是正确结果（暴露真缺陷），也可能是引入新错。
- **决策**：与低风险修复分批——本轮只修"不改变执行语义"的（转义/词表/页签收尾/
  截图丢弃/失败留痕），行为激活类全部挂起，注明"须与真机矩阵轮同做，并预期
  通过率变化"。
- **预防**：修执行引擎类缺陷先分类：语义保持型 vs 路径激活型；后者必须有真机
  回归批次陪伴，否则"修复"会让 100% 通过率的基线失去解释力。

### 46. 子代理修复的验收方式：按真实调用路径读 diff，不读报告（2026-10-08）

- **现象**：适配器子代理报告"GET yaml 打码已完成"——报告属实，但它没意识到
  web 编辑器的 PUT 会把掩码写回（#42）；回放子代理落了 8 项修复，其中 1 项
  （test 前提错误）测试本身写错。
- **方法**：每份子代理产出按三条验收——① diff 逐行读（不只 stat）；② 沿真实
  调用路径走一遍（谁 GET、谁 PUT、谁读这个字段）；③ 其新增测试跑一遍并审视
  前提是否成立（测试也会写错）。
- **预防**：子代理并行修复时，主线程保留"验收人"角色；跨域改动的交界处
  （安全修复×编辑器往返、api 改动×前端消费）是事故高发区，交界处必亲验。

### 47. Hyper-V 动态端口保留会静默吞掉容器端口（JeecG 8095 实锤，2026-10-08）

- **现象**：全部演示容器 Up 8 小时且容器内服务正常（exec 内 curl 200），宿主 8095/8092/8090
  全部连不上；`docker compose up --force-recreate` 报 `bind: An attempt was made to access
  a socket in a way forbidden by its access permissions`；新起随机端口容器（18999）却正常。
- **根因**：Windows Hyper-V/WSL 的**动态端口保留**（excludedportrange）随机漂移，本机当时
  保留了 7998-8097 段——8090/8092/8095 全落界内；运行中的旧容器绑定还在，**重启/recreate
  后才绑定失败**。
- **修复**：管理员 `net stop winnat && net start winnat`（清动态保留）→ recreate 各栈；
  `netsh int ipv4 add excludedportrange ... persistent` 把 8710/9222 等常用口**永久预占**
  （防再次漂移吞口）。
- **预防**：宿主连不上容器端口且容器内服务正常时，第一步查
  `netsh interface ipv4 show excludedportrange protocol=tcp`；演示环境常用口提前永久预占。

### 48. "入口消失"类用户报告先查数据依赖与容量截断（popup 回放列表实锤，2026-10-08）

- **现象**：用户报告"插件里以前能选回放的技能，现在没了"。代码里功能都在（AG3 起）。
- **根因一（数据）**：popup 列表依赖插件 storage 的 `sl_executor_token`，token 7 天过期/
  服务端口令重置 → `GET /executor/skills` 401 → 列表区只渲染一行错误文案——视觉上即"没了"。
  且存在 UX 断链：工作台登录**不会**自动把 token 配给插件（写入只发生在 executor.html?token=
  打开时），用户无自助恢复路径。
- **根因二（容量）**：`slice(0, 20)` 截断——库涨到 288 技能后 JeecG 组（排在 39 位后）整组
  被吞，即使 token 有效也"选不到 JeecG 的链"。
- **修复**：列表全量渲染+搜索过滤（抽 `popup-render.ts` 纯函数直测）+ 401 显示可操作恢复
  指引；真机验证搜索"JeecG"→ 45 行仅 JeecG 组。
- **预防**：带列表的入口类功能，测试必须覆盖"空数据/错误态/大数据量"三态；
  依赖长生命周期凭据的 UI，过期路径必须给自助恢复指引（或自动重配）。

### 49. 链/换参的 override key 语义：fill 步 name，不是变量名（AH 链编排实证，2026-10-08）

- **现象**：链 steps 的 overrides 用 input_variables 变量名（`*表名称`）做 key——
  执行时 seq7 换了、seq5 没换（fill 步 name 是 `*表名`，一字之差），静默不生效。
- **根因**：override 替换的匹配键是 fill 指令的 `name`（录制时的字段 label）或
  录制原值（`ins.value == old`）——变量名只是归纳层的展示名，两者可能不同。
- **修复**：链数据用 fill 步 name 做 key；P2 改进=组链 UI 从技能 input_variables
  自动带出候选 key（含 name/value 两种）。
- **预防**：任何"按名字匹配"的换参/绑定，先 dump 实际指令的 name/value 再定 key；
  静默不生效比报错更危险——匹配 0 次应打日志。

---

*更新记录：2026-09-24 初版（Sprint 0-4 + Sprint 4.5 全自动闭环的踩坑汇总）；
2026-09-24 二版（Windows 移植清单 + 回放水合竞态，§五）；
2026-10-02 三版（§六 S43-4 七系统闭环实战 11 条：#18-#28）；
2026-10-02 四版（#29 链式回放行锚陈旧——JeecG Sync/Fill 收尾）；
2026-10-03 五版（#30 chrome.debugger 桥接回放 AG0 spike 实证）；
2026-10-03 六版（#31 声明式清单不塞复杂 shell——AF2 禅道探针实证）；
2026-10-03 七版（#32 persistent_context 双驱动冲突——AF3 登录验证实证）；
2026-10-03 八版（#33 Odoo 17 密码栈——passlib 权威生成实证）；
2026-10-03 九版（#34 扩展执行器三层坑——AG3 十轮排障实录）；
2026-10-05 十版（#35 动作成功≠效果成功——探针准入+效果验证，zcode 学习落地）；
2026-10-07 十一版（#36 env fallback 写死内网地址红线 + #37 验收路径≠真实路径——P2.5 插件配对 401 静默失效，全量评审实锤）；
2026-10-08 十二版（三轮全库评审沉淀 #38-#46：迁移漂移守卫、非空守卫、模板转义、词表一致性、掩码回填、test.db 并行互撞、"测试恒绿生产必错"三形态、路径激活型修复分批、子代理验收法）；
2026-10-08 十三版（#47 Hyper-V 动态端口保留吞容器口 + #48 popup 回放列表"消失"双根因——JeecG 链路真机矩阵 3 轮 + executor.html 真实路径验收）。*

# 2026-10-09 下半（差距清单+用户报障+AK 块）

## #50 根路径假成功（ERPNext 三连修）
Frappe 根路径 / 对未登录返回 200 SPA 壳，JS 异步跳 login——预检窗口内 URL 不变，单通道 URL 判定必假成功。登录判定必须双通道（URL+title 特征）；title 兼容加入 _logged_in（desk 特征只在 title）。

## #51 首帧补发污染两形态
录制开启补发首帧 navigation（防 SPA 零导航）会记下录制开始的停留页：404 停留页污染系统派生（Odoo 被标 njmind）；跨系统停留页污染 plan url（Odoo 页开录→goto ERPNext）。修法：404 跳过+多数派 host 派生+plan url 取同 host 末条 navigation。

## #52 密码字段采集红线 vs 必填矛盾
录制侧安全红线跳过密码字段（骨架永远无此步），但 ERPNext v15 表单 portal 密码必填——Save 必被拦。runner 密码补步自愈兜底：校验错误含 password required 时定位密码框补填重试（不破红线）。

## #53 MV3 SW 重启丢内存互斥
startRunOnTab 的 execRunning 内存 flag 在 SW 被杀重启后复位——storage.onChanged 重复消费旧请求=重试风暴放大器（131 run/13s 实证）。storage 持久锁（10 分钟过期）兜底+服务端 plan 节流 409（同 skill 5s 内快速失败→拒绝）根治。

## #54 TDZ 中断挂一半
面板 mount() 中 sysEl 定义前同步 addEventListener（TDZ ReferenceError）——DOM 已写一半（模板初值"识别系统中…"）但 detectSystem 永不执行。教训：DOM 引用定义必须在事件绑定前；挂死排查先看模板初值文案是否还在（=流程根本没进）。

## #55 系统识别失败不得放行全部
过滤器 `!systemName || ...` 在识别失败时短路放行全部系统技能——用户在 A 系统页看到全部。识别失败应空列表+明确提示，显式动作（点系统头）才看全部。

## #56 "防线存在≠防线生效"四缺口（attach 风暴复盘，2026-10-09）
风暴再发两场（309+620 条 run）时，节流与 AK 防线代码已提交但未生效。四类系统性缺口：①**部署时间线错位**——常驻进程启动早于防线提交，起环境必须核验进程代码新鲜度（8710 server 与 9222 插件 dist 都要查）；②**前驱状态盲区**——节流只看"最近一条 run"，running 前驱（error 空）放行，互斥/节流类逻辑必须覆盖"未收敛状态"形态；③**收割依赖被动触发**——僵尸 running 清理挂在低频端点顺带跑，挂起的执行页永不清（118 条永卡 5 小时），清理逻辑要么常驻循环要么挂高频入口；④**失败无分类裸 throw**——插件侧 catch 后直接 finish(fail)，无 retryable 判定，SW 重启重复消费时每个复活请求都全新建 run。根治模式（zcode 一手源码）：结构化失败分类+generation 代际校验拒旧请求+stale ref 拒绝。复盘全文：docs/reviews/2026-10-09-attach-storm-retrospective.md。

## #57 测试套件静默收集真机脚本（p0_login_test 地雷，2026-10-10）
scripts/p0_login_test.py 匹配 pytest 默认 `*_test.py` 模式且模块级 `asyncio.run(main())`——每次"全量回归"收集阶段就真连 9222/JeecG 跑面板登录流程，浏览器活着就静默通过、死了就收集错误（URLError）。所有"全绿"声明里都藏着这个活环境依赖（2026-10-08 引入起）。修法：pyproject `testpaths=["tests"]`。预防：运维脚本命名避开 `*_test.py`/`test_*.py`；带模块级执行的脚本永不进收集路径；"测试恒绿生产必错"三形态之外的第四形态——**收集即执行**。

## #58 cwd 漂移让 uv 落到全局 Python（两次实锤，2026-10-10）
从仓库根跑 `uv run pytest`：根无 pyproject.toml，uv 静默用全局 miniconda Python（pydantic v1 ForwardRef 崩）——错误形态是收集 TypeError 而非"找不到项目"，极易误判为代码 bug。Bash 工具 cwd 会随上一条命令漂移。预防：server 侧命令一律显式 `cd /d/github/SkillLens/server &&` 前缀；见收集 TypeError 先 `pwd` 自查。
