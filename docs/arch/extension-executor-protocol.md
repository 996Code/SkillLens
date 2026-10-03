# 扩展执行器协议（Extension Executor Protocol）v0.1

> 块 AG1 契约文档。2026-10-03 起草，TDD 规格——本文档即 AG1/AG2/AG3 的测试依据。
> 配套：主计划 v2.1 块 AG；AG0 spike 实证（lesson #30）。

## 0. 架构定位（与宪法对齐）

```
客户端插件（完整执行节点）              服务器（管理+知识库）
  popup：登录→选技能→【开始执行】         技能库/清单（AF 产物）
    ↓ 用户点击（=C1 授权，含写技能）      计划编译（compile_skeleton_plan）
  SW：attach→步循环→证据回传    ←──→     locate（对快照跑策略链→selector 序列）
  chrome.debugger（CDP 可信输入）         断言评估（evaluate_assertions 原封不动）
                                          四分类/报告/自愈数据链
```

- 服务器**不下发任务**；插件拉取技能元数据，用户点击执行。
- 判定全在服务端（确定性）；插件只执行与采集证据。LLM 只在服务端做提案/归因（边界不变）。
- C3：每步证据、介入过程、run 结果全落库。

## 1. 端点总览（全部走既有 `/api/v1`，Bearer token 认证）

| 端点 | 方法 | 用途 |
|---|---|---|
| `/executor/skills` | GET | 技能列表（含 requires_confirmation/write_steps 元数据，按角色过滤） |
| `/executor/skills/{id}/plan` | POST | 编译计划：入参 overrides+confirm_side_effect（客户端 C1 已点击）→ 返回 run_id+首条指令 |
| `/executor/runs/{run_id}/step` | POST | **步循环主端点**：上报上一步证据 → 返回下一条指令 |
| `/executor/runs/{run_id}/snapshot` | POST | 大快照/截图分块上报（复用 events 通道格式） |
| `/executor/runs/{run_id}/finish` | POST | 收尾：detach 后上报终态（用户停止/浏览器关闭也走此） |

## 2. 指令集（服务端 → 插件）

所有指令公共字段：`{seq, op, timeout_ms}`。

| op | 载荷 | 语义 |
|---|---|---|
| `goto` | `{url}` | Page.navigate + domcontentloaded 等待 + 2s 余量（同现 runner 语义） |
| `snapshot` | `{phase: "before"\|"after"\|"repair", scopes: ["labels","forms","toasts","rows"]}` | 采页面快照（复用采集端 snapshot.ts 同 schema） |
| `resolve` | `{selectors: [...], frame_hint}` | 按序尝试候选 selector（服务端 locate 产出），返回首个命中元素的 rect+可见性+enabled；全不命中→上报 miss（触发介入，见 §4） |
| `click` | `{rect, trusted: true}` | scrollIntoView→取 rect 中心→Input.dispatchMouseEvent pressed+released |
| `fill` | `{rect, value, verify: true}` | click 聚焦→Input.insertText→JS hook 确认 value 生效（水合回写则重填≤3 次，lesson #15 语义） |
| `press` | `{key}` | Input.dispatchKeyEvent（Enter 提交类） |
| `wait_events` | `{url_template, method: "POST", timeout_ms}` | 等 Network 域响应命中（写判定，lesson #18 intercept+wait 语义）；listener 先订阅后动作（lesson #30 时序） |
| `poll_toasts` | `{selectors}` | toast 轮询例程（等待窗口内并发跑，结果随下一步证据上报） |
| `screenshot` | `{kind: "step"\|"final"}` | Page.captureScreenshot |
| `heal` | `{retry_from_seq, patch}` | 当轮修复重试：表单换值（field_types 产物）或提案 selector |
| `detach` | `{}` | 结束，收横幅 |

## 3. 证据上报（插件 → 服务端，随每次 step）

```json
{
  "seq": 3,
  "result": "ok | miss | timeout | error",
  "evidence": {
    "network": [{"url": "...", "status": 200, "method": "POST", "body": "...", "latency_ms": 120}],
    "toasts": ["添加成功!"],
    "snapshot_ref": "blob-id（大对象经 /snapshot 分块）",
    "screenshot_ref": "blob-id",
    "value_after": "实际生效的输入值（fill verify 产物）",
    "validation_errors": [{"selector": "...", "message": "请输入正确手机号"}],
    "page_title": "禅道...",
    "env": {"user_agent": "...", "viewport": "..."}
  }
}
```

- `network.body` 客户端截断 100KB（同服务端 MAX_BODY 纪律）；脱敏红线同采集侧。
- C1/C2 标记：run 元数据带 `executor=extension`，source 延续 demo|real_traffic 分轨。

## 4. 当轮 LLM 介入（超时/未识别时）

```
插件 resolve miss/超时
  → 上报 {result: "miss", evidence: [现场快照+截图]}
  → 服务端：generate_proposals（LLM 从快照 texts/forms 选新标签——输入纯数据）
  → 服务端：提案编译成 resolve 指令（selectors 按提案 label 重算）
  → 下发 heal {retry_from_seq} ——当轮验证（页签还开着）
  → 命中：继续步循环；未命中：run 内介入计数 +1
  → 计数 > 2：判 fail 留下轮（跨 run 自愈——record_usage 数据链不变）
```

铁律：LLM 只提案；**命中判定=resolve 实测**（确定性）。介入全程入 llm_call_log（C3）。

## 5. 错误路径（必须处理，AG0 实证形态）

| 场景 | 客户端行为 | 服务端行为 |
|---|---|---|
| attach 冲突（"Another debugger is already attached"） | 上报 `error`+detail，提示用户关闭 DevTools | run=error，attribution 记录 |
| 用户点 [停止] | 立即 detach→finish {status:"aborted"} | run=aborted；已采证据保留（C3） |
| 用户关横幅/关页签 | onDetach 事件→finish {status:"aborted"} | 同上 |
| 网络断连 | 证据入 IndexedDB 缓冲，恢复后重放 step 请求（幂等：seq 去重） | seq 重复丢弃，返回已缓存的下条指令 |
| SW 意外死亡（运行中） | 用户 popup 仍开→重连续跑；否则 finish 缺失→心跳超时 | run=lost（新状态），60s 后释放 |

## 6. C1 确认卡（popup 侧）

执行前展示：`requires_confirmation=true` 的技能显示写步骤清单（label×次数，
数据来自 plan 编译期），用户点【开始执行】=对整批授权。读技能无卡直接跑。
服务端 `/executor/skills/{id}/plan` 仍校验 `confirm_side_effect` 参数（双保险）。

## 7. 版本

v0.1（2026-10-03）：初稿。AG1 红测试以此为准；变更需更新本节。
