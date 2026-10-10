# AM 块：期望-观测对比异常检测（设计）

> 2026-10-10 立项。触发：用户提问"我们不知道正常应该返回什么效果吗？
> 根据正确去对比是不是就能知道异常了？"——方向裁定+全权委托。
> 定位：**语义层异常检测主干**。与 AK（机制层：四码处置）和 AJ1
> failure_class（归因层）正交互补。

## 一、问题：静默失败是检测盲区

四码分类只能抓"报出来的错"（异常/超时/取消）。抓不住**静默失败**——
操作机制上"成功"但世界没变：

| 实证 | 形态 | 四码能抓吗 |
|---|---|---|
| ERPNext 登录假成功 | URL 判定 200 SPA 壳，实际在登录页 | ❌ 无异常抛出 |
| run 2817（JeecG skill 40） | click"新增"报 ok（login 页误命中），后续 fill 全 miss 烧完 120s 预算 | ❌ 步级报 ok |
| 提交被表单校验拦截 | click ok，无 API 请求，表单不关 | 服务端✅（写水位）/插件端❌ |

## 二、答案：期望-观测对比（用户直觉 = 业界共识）

**期望从证据学习（C3），观测在执行期采集，对比即检测**——不需要异常
抛出，分歧本身就是异常信号。成熟系统同款：

- **Frappe 官方 cypress**（S43-4 实证）：提交判定=等写请求，非解析
  toast 文案——写请求就是"期望的效果"。
- **zcode 效果验证**（lesson #35：动作成功≠效果成功）：点击后读回
  状态核实（setChecked 读回模式）。
- **Playwright auto-wait**：动作前验证可操作性，动作后隐含等待效果。
- **SkillLens 自己已有的**：服务端 runner 写水位（"点击后无写请求"
  步级失败）；AG4 finish 断言评估（observed vs outcome_assertion）；
  AJ2 登录守卫（URL+title 双证据）；from-run 断言反哺（期望从 pass
  run 的观测学习）。

**缺口**：期望对比在**插件执行路径的步级**缺失——executor 的 click
报 ok 不核效果；goto 落登录页不识别（服务端有守卫，插件端没有）。

## 三、切片（TDD）

| # | 切片 | 侧 | 验收 |
|---|---|---|---|
| AM1 | 写效果水位（步级）：submit 类 click 后必须观测到写请求（POST/PUT/PATCH 响应入 networkLog），否则步 fail"点击后无写请求（提交被拦截）"——与服务端 runner 同语义，plain_errors 已有白话映射 | extension | 纯函数单测+真机 |
| AM2 | 登录守卫（goto 级）：goto 后页面 URL 落 login 路径 → 快败 e1_env+白话"登录态丢失"——词表与服务端 failure_class._LOGIN_URL_RE 同源（双端一致性测试锁定） | extension | 纯函数单测+真机（skill 40 登录卡死场景=验收用例） |
| AM3 | （后续批）期望数据闭环：断言未过/效果未触发/定位失败三态在 run 报告分列 | 双端 | 报告可读性 |

## 四、不做（边界）

- 不做插件端自动登录恢复（适配器例程经 CDP 执行是独立特性，挂后续）
- 不做全量 DOM 快照 diff 对比（成本高噪声大——写请求+URL 是高信号窄期望）
- 不改 AK 四码/failure_class 语义（正交，只消费）

## 五、落地记录（2026-10-10，AM1+AM2 完成）

### 实现形态

- **AM1 期望声明（服务端编译期）**：`expect_write` = **证据派生 ∪ 词表兜底**
  - 证据派生（`plan.py expect_write_from_events`）：录制时 click 后
    （到下一 action 事件前）有写请求 → 声明。比词表准：JeecG 模态提交
    「确定」命中（词表刻意排除防搜索框误报）；搜索「确定」（后随 GET）
    不命中；两步提交 Submit→Yes 天然自豁免。
  - 词表兜底（`expect_write_for`，WRITE_EXACT/WRITE_SUB 单一源）：
    net-hook 经典表单盲区（录制无写证据）时 save/submit 族仍声明。
  - runner 步循环改消费 plan.py 常量（词表漂移守卫测试锁定）。
- **AM1 观测对比（插件端步循环）**：expect_write 指令执行后 6s 内
  networkLog 写响应水位未涨 → 步 error「点击后无写请求（提交被拦截）」
  快败。预拉放行（上步末水位）与服务端 runner 同语义。
- **AM2 登录守卫（插件端 goto 级）**：goto 后 URL 落 login 路径（词表
  与服务端 failure_class._LOGIN_URL_RE 同源）→ 步 error「登录态丢失」
  快败，归因带 URL 脱敏（C3）。
- 纯函数：`extension/src/shared/expectations.ts`（8 用例）。

### 真机验证（9222 真实执行页路径，JeecG）

| 场景 | run | 修复前 | 修复后 |
|---|---|---|---|
| 登录态丢失 | 2819 | 120s 预算烧尽+9 步 miss+归因不可读（2817） | goto 步秒败「登录态丢失…请先登录」 |
| 提交被拦（duplicate） | 2822/2825 | 步报 ok 静默漏到断言层（2820） | 提交步快败「点击后无写请求」+库级证实零写入 |
| 金路径（正常提交） | 2826 | — | 写请求观测到→放行→pass（无假阳性） |

### 真机抓到的坑

- **词表盲区（2820 实证）**：JeecG 模态提交按钮是「确定」——词表刻意
  排除（防搜索框 GET 误报）导致 AM1 初版漏检 → 升级为证据派生∪词表。
- **模块级常量名冲突**：plan.py 已有 `_WRITE_METHODS=("POST:",...)`
  （签名格式），新增同名元组被覆盖（"POST" in ("POST:",...)=False）→
  改名 `_AM_WRITE_METHODS`。教训：加常量先 grep 同名。
- **override key 语义**（lesson #49 复现）：`fill_表名` 不生效（key=fill
  步 name「*表名」）——错 key 的换参跑出 duplicate，恰好成为 AM1 的
  真实验收场景。

### AM3 落地记录（2026-10-10，期望三态呈现）

- **failureKind 纯函数**（web/src/run-format.ts）：失败步语义三态
  locate（定位失败）/effect（效果未触发——AM1 写水位/AM2 登录守卫
  产出形态）/error（其余）。词表与 plain_errors._DETAIL_PATTERNS 同源锚。
- **插件 run 步骤合成**（replay.py get_run）：插件 run executed 恒空
  （executor 只发 observed——步结果在 plan.executor_state.received）→
  详情端点把 received+instructions 合成 executed 形态。run 详情页
  步骤表从"无步骤记录"变为全步骤呈现（服务端 run 原值直通）。
- **视图三态标签**（ReplayRunView）：失败步下方白话提示行。
- 真机验证（run 2822=skill 40 提交被拦格）：19 行步骤呈现+失败步
  「效果未触发——操作成功但预期结果未发生」标签。
- 测试：web 81/81（failureKind 3 用例）+replay API 11/11（合成用例）。
