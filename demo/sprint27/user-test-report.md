# Sprint 27 用户测试报告：试点彩排（K 块技术就绪验证）+ LLM 解析器加固

> 日期：2026-09-28 · 依据用户指令"能自验的闸口全自闭环"——G4 试点团队是外部组织输入
> 无法代理，但**试点技术就绪**可彩排验证：在真实 njmind 上以"试点团队一天"的
> 完整产品路径跑通全链路。模型按用户指令切换 kimi-k3-oc（多模态）。

## 一、彩排全链路结果（真实环境，全程常驻可见浏览器）

| # | 试点团队会做的事 | 结果 |
|---|---|---|
| 1 | 装插件、日常操作 njmind | ✅ auto_record 两轮真实采集（13 事件/轮：input+保存 click+8 API） |
| 2 | 系统自动学习 | ✅ process→align（双会话）→induce→**skill 13 SaveFormWithTableConfig learned**（kimi-k3-oc 命名）→5 条断言 |
| 3 | C1 影子核验 | ✅ shadow run 65（未确认不触浏览器） |
| 4 | 确认后真实回放 | ✅ execute run 66 **PASS**（5 断言全过，真实 njmind 页面） |
| 5 | 提需求等发版 | ✅ expected delta（external_ref=PILOT-001）→confirm→observe（真实回放）→**report #9**（expected 2/missing 0/unexpected 6/drift 0 + 性能上下文：基线 2359ms/本次 1719ms） |
| 6 | 收通知 | ✅ **Webhook 端到端送达**（本地接收器收到 wecom 格式：报告生成 + 画布运行完成两条） |
| 7 | 跑定向回归流水线 | ✅ 画布运行 #6 finished |
| 8 | 晨间评审 | ✅ reviewer1 登录评审 run #6 approved（review #2，绑定真实账号） |
| 9 | 工作台查看 | ✅ 报告 #9 页四分类+性能区块、skill 13 详情渲染正常，截图入库 |

**结论：试点团队从拿到系统到完成一个完整使用日所需的全链路，技术就绪验证通过。**

## 二、彩排中抓出并修复的真实缺陷（TDD）

**parse_llm_skill 贪婪正则缺陷**：思维链模型（glm-5.3-oc 实测）输出散文+**重复
JSON 块**，贪婪 `\{.*\}` 跨块匹配非法 JSON → skill 降级 Candidate。修复：枚举全部
`{...}` 候选从后往前取首个含 name/description 的可解析对象（末块=定稿）。
kimi-k3-oc 输出纯 JSON 不受影响，但解析器对两类模型均健壮（3 个新单测）。

## 三、环境观察（记录在案）

- kimi-k3-oc 网关**间歇 500**（首调失败重试即通，C3 已把失败调用落库且 URL 脱敏——
  失败路径在真实环境验证了）；建议私有化部署配重试或网关侧探活。
- LLM 429 限流（qwen 时期）同样被 C3 正确捕获——彩排顺带验证了失败落库链路。

## 四、截图

- `screenshots/01-report9.png`：彩排报告 #9（四分类+性能区块）
- `screenshots/02-skill13.png`：彩排学到的 skill 13 详情
