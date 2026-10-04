# 扩展执行器协议（Extension Executor Protocol）v0.2

> 块 AG1 契约文档。2026-10-03 起草 v0.1，同日 v0.2 对齐实测实现
> （AG5 验收后全量校准——v0.1 的设计前瞻项标注为"预留"）。
> 配套：主计划 v2.1 块 AG；AG0 spike 实证（lesson #30）。

## 0. 架构定位（与宪法对齐）

```
客户端插件（完整执行节点）              服务器（管理+知识库）
  popup：选技能→跳转执行页               技能库/清单（AF 产物）
  executor.html：C1 确认→点击执行        计划编译（compile_executor_plan）
  chrome.debugger（CDP 可信输入）        resolver 候选编译（AF2 后置 AG2）
  步循环：交证据换指令                    断言评估（evaluate_assertions）
                                        当轮 LLM 介入（miss→提案→heal）
```

- 服务器**不下发任务**；用户点击执行（写技能点击=C1 授权，auto=1 为
  验收模式由调用方持授权）。
- 判定全在服务端（确定性）；插件只执行与采集证据。
- C3：每步证据、介入过程、run 结果全落库（executor=extension 标记）。

## 1. 端点总览（全部走既有 `/api/v1`，Bearer token 认证）

| 端点 | 方法 | 用途 | 状态 |
|---|---|---|---|
| `/executor/skills` | GET | 技能列表（含 requires_confirmation） | ✅ |
| `/executor/skills/{id}/plan` | POST | 编译计划→run_id+首条指令 | ✅ |
| `/executor/runs/{run_id}/step` | POST | 步循环主端点（seq 幂等+当轮介入） | ✅ |
| `/executor/runs/{run_id}/finish` | POST | 终态+断言评估（done→pass/fail 重判） | ✅ |
| `/executor/runs/{run_id}/snapshot` | POST | 大快照分块 | 预留未实现 |

## 2. 指令集（服务端 → 插件）

实际产出 **5 op**（compile_executor_plan；定位语义经 resolve_candidates
内联，独立 resolve op 不需要）：

| op | 载荷 | 语义 |
|---|---|---|
| `goto` | `{url}` | 先访问 origin 清 localStorage（hash SPA 视图记忆）→导航→2.5s |
| `snapshot` | `{phase: before\|after}` | 页面 url/title 快照；after 前留 2.5s 晚到响应窗口 |
| `fill` | `{name, value, labels, resolve_candidates}` | scrollIntoView→重取 rect→mouseMoved 聚焦→insertText→读回验证→blur（onchange 触发链） |
| `click` | `{label, labels, tag, resolve_candidates}` | 同上 scroll/hover 语义；8 轮重试（第 4 轮 reload） |
| `detach` | `{}` | 结束收横幅 |

resolve_candidates：服务端 locate 策略矩阵编译的有序候选（title-attr/
aria-attr/role-button/form-group×2/select2/menuitem/menuitem-css/text/
placeholder/el-select/label/id/name-attr/row-anchor），插件端按序实测
（可见谓词；els 唯一才命中）。miss→触发 §4 介入。

预留 op（未实现）：press/wait_events/poll_toasts/screenshot/poll_heal。

## 3. 证据上报（插件 → 服务端，随每次 step）

实际字段：`{seq, result: ok|miss|unsupported, evidence: {network[]（含
method+body 截断）, toasts[], page{url,title}, page_texts[]（miss 时——
介入输入）, value_after（fill 读回）}}`。预留：snapshot_ref/screenshot_ref/
validation_errors/env。

## 4. 当轮 LLM 介入（miss 时，✅ 已实现）

miss → 服务端 LLM 从 page_texts 提案（落 LocateProposal proposed）→
提案 label 重编译候选 → healed 指令重试当前步（seq 不推进）——**判定=
插件端 resolve 实测**（确定性）。每 run 上限 2 次；超限继续原指令序列
（如实 fail 由断言层判）。铁律：LLM 只提案，判定确定性。

## 5. 错误路径

| 场景 | 客户端 | 服务端 |
|---|---|---|
| attach 冲突 | fail+提示关 DevTools | ✅ |
| 用户停止/关横幅 | finish aborted | ✅（onDetach 监听 P1 待补） |
| 断连重放 | seq 幂等丢弃 | ✅ |
| SW 死亡/finish 缺失 | — | 心跳 60s→lost 预留未实现 |

## 6. C1 确认卡（executor.html）

写技能显示确认卡（requires_confirmation 元数据）；auto=1 跳过（验收/
编排场景——授权由调用方持有）。服务端 plan 端点仍校验 confirm_side_effect
（双保险）。

## 7. 版本

v0.1（2026-10-03）：初稿（设计前瞻版）。
v0.2（2026-10-03）：对齐 AG5 实测——指令集 5 op、finish pass/fail 重判、
证据 schema 实际化、介入实现化；前瞻项标"预留"。
