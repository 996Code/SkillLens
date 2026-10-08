# Playwright 深层工程设计调研（2026-10-08，多 agent 学习第 1 路）

> 调研员报告全文收录。SkillLens 对应物映射已含在正文。来源：playwright.dev 官方文档。

## 一、报告数据模型：HTML Report / JSON Report

四层树：`suites → specs(TestCase) → results(TestResult) → steps(TestStep)`，附件挂 result 与 step 两级。
**每次重试是 results 数组里的独立 TestResult**（含 retry 序号/duration/workerIndex）。
TestStep 自带 category（expect/fixture/hook/pw:api/test.step）+ 独立 error + attachments。
Attachment 结构极简：`{name, contentType, path|body 二选一}`——**附件只引用不内嵌**。
HTML 报告自包含文件夹，附件存 data/ 子目录；"Copy prompt for errors" 一键生成喂 LLM 的错误上下文。

**精髓**：结构与呈现分离（一套数据模型喂所有 reporter）；重试历史天然内嵌 results 数组，
**flaky 是 outcome 四态之一**（expected/unexpected/flaky/skipped）而非独立存储。

**对 SkillLens**：executed[] 对齐 TestStep 补 category/startTime/duration/error/附件引用；
artifact_path 升级为 attachments 列表（step-NN.png 精确挂步骤）；
attribution 结构化为 call log 风格（等待了什么/重试了什么）。

## 二、Trace Viewer：事后可回放调试

每测试一个 trace.zip：action 的 locator/时长/源码位置 + **DOM 快照序列**（Before/Action/After
三类，Action 快照精确到点击落点坐标）+ screencast + console（浏览器/测试双来源）+ 全量网络。
采集策略按结果挂钩：**retain-on-failure**（成功即删）/on-first-retry（默认）。
Viewer 是纯前端+zip 数据包，**数据完全本地加载不上传**。

**精髓**：DOM 快照序列代替全帧视频——序列化 DOM 是可交互、可 Diff、体积可控的"时间数据库"；
采集成本与失败挂钩让默认开启成为可能。

**对 SkillLens**：CDP 采集端已捕网络与 DOM 事件，距"快照序列"只差按 action 边界切片落盘。
落地：fail 时保留完整步骤截图链+observed 切片打包为 run 级 artifact，成功只留摘要
（retain-on-failure——C3 全链路落库与存储成本的平衡）。

## 三、test.step() 与软断言

test.step() 声明报告可见的命名步骤（嵌套/box 错误定位到调用点/params 序列化进报告/skip）。
**expect.soft()：失败不终止，所有失败收集进 testInfo.errors，run 末统一判 fail**——
"单页面多处验证一次跑完收集全量证据，归因价值远大于首败即停"。

**对 SkillLens**：assertion_results 是列表结构天然适合软断言——所有断言都执行、失败不中断、
run 末统一判定；与 OutcomeAssertion 的 evidence_count 累积（≥3 轮 verify 升级）完全咬合。

## 四、重试语义

**每次尝试都生成独立 TestResult 全部进报告**；outcome 三分类 passed/flaky/failed。
失败隔离靠 **worker 进程级边界**（失败即丢弃进程+浏览器重启——污染不跨测试传播）。
serial 组失败后组内 skip；**官方明确默认推荐隔离**（可重试性是架构属性）。

**对 SkillLens**：ReplayRun.flaky 已对齐但只存最终结果——补 attempts 数组；
链编排前置节点 fail 后续应标 **skipped 而非 fail**（"没跑"≠"跑了没过"）。

## 五、projects 机制

声明式正交矩阵：projects 数组+devices 注册表；顶层共享 project 覆盖（retries/baseURL/channel）。
**依赖项目**：dependencies:['setup'] 登录先跑，失败则依赖项目不跑；setup 可声明 teardown。

**对 SkillLens**：链编排是天然 project 对应物——引入 profile 概念（影子vs真实/服务端vs插件/
换参矩阵组合）；前置登录节点=setup 依赖项目语义（链编排 v2 的 setup 已实现此语义的前半）。

## 落地优先级 Top5

| # | 项 | 对应物 | 成本 |
|---|---|---|---|
| 1 | executed[] 对齐 TestStep（category/时间/附件引用） | ReplayRun.executed | 低（改 dict） |
| 2 | 断言软收集（全量执行不中断，run 末统一判） | assertion_results+evidence_count | 低 |
| 3 | 附件列表化+retain-on-failure | step-NN.png/artifact_path | 中 |
| 4 | attempts 数组（重试历史可追溯） | ReplayRun.flaky | 中 |
| 5 | trace 式证据包（截图链+observed 打包） | observed/CDP 采集 | 高（roadmap） |

Sources: playwright.dev/docs/{test-reporters, trace-viewer-intro, trace-viewer,
api/class-test, api/class-teststep, api/class-testcase, api/class-testinfo,
test-assertions, test-retries, test-projects}
