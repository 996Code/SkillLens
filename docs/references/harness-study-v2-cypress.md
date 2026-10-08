# Cypress 调试与开发体验调研（2026-10-08，多 agent 学习第 2 路）

> 来源：docs.cypress.io 官方文档。已与 SkillLens 现状逐项对照。

## 一、时间旅行与快照

每条命令自动拍 DOM 快照（内存中，open 模式默认留 50 测试）；悬停 Command Log
即恢复该时刻 DOM+URL；操作命令显示红色 hitbox；可固定（pin）快照深查。

**对 SkillLens**：采集端已有锚点前后 2.5s 语义快照（state_before/after），**回放端没对齐**。
建议：回放每锚点步复用 collect_page_snapshot 旁挂 executed；run 详情页步骤行悬停显示
该步快照+截图——"穷人版时间旅行"，成本低。

## 二、Command Log（性价比最高项）

编号命令 vs 无编号灰色事件条（XHR/URL 变化/页面加载）**交织同一时间线**——
"用户操作流"与"系统响应流"的因果关系一眼可读。点击命令→控制台结构化输出。
**cypress tap**：CLI 读命令日志，明说是给 AI 编码代理用的——"命令日志本身就是数据 API"。

**对 SkillLens**：数据已齐（observed 网络事件/executed/toast），但落库时网络按模板聚合
丢失了"第几步触发哪个请求"的交织关系。建议：executed 条目旁挂步内网络事件引用，
详情页渲染交织时间线；暴露结构化步骤日志 JSON 端点（tap 对应物）——AI 编排产品供料。

## 三、自动等待（Retry-ability）

**"等待的尽头是重试查询，不是 sleep"**——断言失败从链顶重跑查询链直到超时收敛
（DOM 更新后毫秒级通过 vs 固定 sleep 赌最坏情况）。动作内置可操作性断言但只执行一次。

**对 SkillLens**：locate 12×1s/写水位/flaky 重跑已同构。**差距在断言层**：ui_text 等
在计划执行完后一次性评估，无重试窗口。建议：断言失败→有界窗口内重采快照→超时才 FAIL，
重试轮数进断言明细（零成本 flaky 预警信号）。同时吸取反面教训：给单步定位设总量预算
（债务：locate 内外重试叠加最坏 44s 无预算）。

## 四、HMR/Watch

Cypress 只做"工具链热更新→自动跑测试"的事件桥接，不自造构建链。

**对 SkillLens**：①评审门户保存 label/overrides 后自动触发 shadow 回放（零风险 C1 兼容）；
②run 详情页"从该步重跑"而非整 plan（execute_plan 步循环+seq 幂等已支持）。

## 五、Cypress Studio（重要事实修正）

**Studio 未被移除**——15.4.0 移除实验标志是因为**转正为默认行为**，现 Beta+Studio AI
（LLM 断言推荐逐条 Accept/Reject）。
关键设计：只录 5 类命令（宁录得少不录不可靠的）；**扩展已有测试时只追加不改中段**
（保护用户心智所有权）；AI 推荐逐条接受/拒绝非整包（LLM 可信度的正确交互形态）。

**对 SkillLens**：录制面收窄是刻意设计（与我们宁缺毋滥同源）；repair 提案 rejected/verified
状态机已同构 Studio AI 的交互形态，保持逐条粒度；可引为成熟项目对照论据。

## 六、cy.intercept 与 flaky 治理

三级：spy/静态 stub/动态 handler。flaky 关键用法：`cy.wait('@alias')` 等**完整请求响应
周期**（比等 UI 元素本质）；`times:1` 失败一次后恢复注入；forceNetworkError 模拟断连
（区别于 500）；throttleKbps 慢网复现竞态；blockHosts 屏蔽第三方噪声。

**对 SkillLens**：写水位已学到位（intercept+wait 同构）。差距在**注入侧**：net-hook 纯被动。
可落地：CDP Fetch 域屏蔽分析域名回 503（降噪）；诊断模式注入 delay 复现竞态。
**任何 stub 业务响应的回放必须打 mode 标记与真实回放分轨（C2），默认关闭**。

## 落地优先级 Top5

| # | 项 | 价值/成本 |
|---|---|---|
| 1 | 步骤-事件交织时间线（executed 旁挂网络事件引用+前端渲染） | 数据已有，只差落库与渲染 |
| 2 | 结构化步骤日志 JSON 端点（cypress tap 对应物） | API 加法，AI 编排供料 |
| 3 | 每步语义快照+悬停查看 | 采集端已同构，回放端对齐 |
| 4 | 断言有界重试+重试计数披露 | settle 语义扩展，flaky 预警 |
| 5 | 回放网络降噪（blockHosts 式 CDP 拦截） | 成本高，C2 约束，长期价值 |

主要出处：docs.cypress.io/app/{core-concepts/open-mode, core-concepts/retry-ability,
references/configuration, references/experiments, guides/cypress-studio,
component-testing/component-framework-configuration}、docs.cypress.io/api/commands/intercept
