# Sprint 4 验收记录：njmind 真实回放 E2E（演示 3 预演）

日期：2026-09-24。Skill #1 `SaveFormAndTableConfig`（Sprint 3 诱导，置信度见 skill 表），
参考表单 `ceshi000001`（可重复保存），登录态经 `REPLAY_STORAGE_STATE` 注入（admin 账号，
验证码留空登录，storage_state 存本机 /tmp，不入库不进仓库）。

## 验收标准（spec §7 Sprint 4）

> 换一组参数自动回放，正确判定 PASS；破坏一个断言能判 FAIL。

## 结果总览

| # | run | mode | status | 说明 |
|---|-----|------|--------|------|
| 1 | run 1/2/6 | shadow | shadow | C1：未确认不启浏览器，返回编译好的计划 |
| 2 | run 10 | execute | **pass** | 换参数回放：`请输入` 注入 `replay-e2e-005`（原始值 `wenbenshurukuang2321`），3 步全过 + 4 断言全 PASS |
| 3 | run 11 | execute | **fail** | 破坏断言（expect_status 200→500）→ 判 FAIL + 截图 + LLM 归因；验证后已恢复 |

## PASS 证据（run 10）

- 执行（语义定位，strategy 非 CSS）：
  - `input 请输入` → strategy=placeholder，ok
  - `click 请输入` → strategy=placeholder，ok
  - `click 保存` → strategy=role-button，ok
- 断言 4/4：
  - `/codeBack/formConfig/saveFormConfig` 200==200 PASS
  - `/codeBack/tableConfig/getTableConfigByFormConfigId` 200==200 PASS
  - `/codeBack/tableConfig/saveTableConfig` 200==200 PASS
  - `/codeBack/tableConfig/saveTableConfig` `code`==200 PASS
- 完整 JSON 见 `replay-result.txt`（PASS run 10 + FAIL run 11）。

## FAIL 证据（run 11）

- 构造：SQL 将断言 2 `expect_status` 200→500，回放后恢复（当前 DB 断言 2 已恢复 200）。
- 判定：仅断言 2 FAIL（观察 200 ≠ 期望 500），其余 3 条 PASS → status=fail。
- 截图：`server/artifacts/replay-1790215799581.png`（149,572 字节，非空白）。
- LLM 归因（llm_call_log id=5，purpose=replay_failure_attribution）：
  > 获取表格配置接口实际返回状态码200，与断言期望的500不符导致失败。可能是预期的服务器错误场景未触发，或该接口已修复正常。

## 真实生效证明（副作用）

回放真实保存了表单：诊断期表单标题已变为 `replay-e2e-003 - 表单设计器`（上一次回放的
override 值），本轮 PASS 后为 `replay-e2e-005`。即"AI 替用户操作软件"端到端真实发生，
非模拟。

## 回放期间发现并修复（fix1–fix6）

| fix | 提交 | 问题 → 修复 |
|-----|------|-------------|
| fix1 | 6dd36e8 | 参考无 navigation 事件 → plan.url 空 → 兜底取首个 action.payload.url |
| fix2 | 86e2fb2 | 计划混入非骨架步骤（8 步）→ compile_skeleton_plan 只从骨架窗口编译 |
| fix3 | a4c0e64 | 回放无登录态 401 → REPLAY_STORAGE_STATE 注入 new_context |
| fix4 | c216b1e | goto 后立即执行 → 空白页 → domcontentloaded(15s)+2s 渲染等待 |
| fix5 | d9318d0 | page.on("response") async 回调静默不触发（observed=0）→ 同步壳+create_task |
| fix6 | 6a4befa | 固定 1.5s 收尾漏链式请求（saveTableConfig 晚到）→ 断言模板驱动收尾等待（全命中即止，上限 10s） |

## Sprint 回顾（spec §12）

- **#5 C1 零违规**：shadow 未确认绝不启浏览器——run 1/2/6 均未启动浏览器；execute 仅在
  `confirm_side_effect=true` 且用户在旁观察下执行（用户 2026-09-24 授权 admin 账号全自动操作）。
- **#8 LLM 只归因不判定**：PASS/FAIL 由 evaluate_assertions 确定性计算；LLM 仅在 fail/error
  后生成 attribution 文本，全程落 llm_call_log。
