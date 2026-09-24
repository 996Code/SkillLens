# UI Before/After 状态快照（Sprint 8，块 B）架构与语义

> 状态：随 Sprint 8 T1/T2 落地，T3-T5（ui_text 断言/回放快照/E2E）进行中。
> 本文回答"快照从哪来、怎么归属、边界在哪"，是采集与消费两侧的契约文档。

## 1. 这层解决什么问题

njmind 表单设计器的 `saveFormConfig` reqBody 约 100KB（全量配置 JSON）但**字段默认值不在其中**（Sprint 3 发现）——纯网络证据测不出"默认值变了"这类 UI 语义变化。本层在锚点动作前后采集轻量 UI 状态（表单值/状态标签/表格行数），补齐 Outcome 层 2 的 UI 证据（宪法 spec §4.3 层 2(b)，Sprint 5 跳过项）。

## 2. 数据流

```
插件 CS（capture.ts）
  锚点动作（click/submit）处理分支
    ├─ 同步：emit("snapshot", {phase:"before", ...})   ← seq 先于 action 事件
    └─ setTimeout 2500ms：emit("snapshot", {phase:"after", ...})
  （走既有 EVENT_MSG → SW → 批量上报通道，零协议改动）
        ↓
server Ingestion
  raw_event（kind="snapshot"，C3 落库）
        ↓
  process.py assign_snapshots(events, windows)   ← 独立纯函数，不碰切窗/members
    归属规则：before → 下一个锚点窗（多张取最靠近锚点者）
             after  → 前一个锚点窗（多张取最后）
             无归属（录制结束后才触发的定时器等）→ 丢弃
        ↓
  semantic_action.state_before / state_after（JSON，nullable）
```

## 3. Snapshot 结构与红线

```ts
{ phase: "before" | "after", ts: number,
  forms:  { label: string, value: string }[],   // ≤50 字段，单值 ≤1024 字符，超出 overflow=true
  labels: { text: string }[],                   // [class*=tag|status|badge]，≤20 条 × ≤200 字符
  tables: { label: string, rows: number }[],    // ≤10 张，rows=tbody tr（无 tbody 则 tr-1）
  overflow?: boolean }
```

- **密码框整体跳过**（连 label 都不落）。
- **敏感 label 脱敏**：label 命中 `SENSITIVE_KEY_RE`（password/token/secret/authorization/cookie）→ value 复用既有 `redactValue` 掩码——与输入通道同一条红线。
- label 解析复用 `describe-element`（aria-label → placeholder → title → 关联 label → 累积文本），不发明新选择器格式。

## 4. 归属语义与已知边界（设计内取舍）

| 场景 | 行为 |
|---|---|
| before 快照 ts == 锚点 ts | 归该锚点（capture 侧 before 先于 action 同步发射，同毫秒属常态） |
| 相邻锚点间隔 < 2.5s | 前一锚点的 after 落在后一锚点之后 → 归给**后一**锚点（快点击下 UI 本就未稳，差异可忽略） |
| 连点风暴 | pendingAfter 挂起上限 8：第 9+ 锚点保 before、跳过 after（防定时器堆积） |
| 多张 after 同窗 | 取最后一张（最新状态） |
| 快照事件混入事件流 | 切窗（windows.py 只认 action/network）、对齐签名、api_calls、state_signals、input_variables、回放计划、field_change 九条既有消费路径**均不消费 snapshot**（审查逐条核实+防污染测试锁定） |
| 截断值口径 | MAX_VALUE_CHARS=1024 按 UTF-16 字符计，中文场景 UTF-8 字节可达 ~3KB（已知偏差，消费侧另有 8KB 行级截断兜底） |

## 5. 迁移与兼容

- `semantic_action` 新增 `state_before/state_after`（JSON nullable，迁移 `c9d41f2a7e03`，up/down 对称）。
- 旧会话（无快照事件）两列为 NULL，全链路零影响（向后兼容测试 `test_process_without_snapshots_state_null`）。
- `RawEventIn.kind` 扩展 `"snapshot"`（加法变更）。

## 6. 测试地图

| 层 | 文件 | 覆盖 |
|---|---|---|
| 插件 | `snapshot.test.ts`（6 用例） | forms/tables 采集、50 上限+overflow、密码框跳过、1KB 截断、敏感 label 脱敏 |
| server | `test_process.py`（+3 用例） | before/after 归属 + api_calls 防污染、无快照全 None、多 after 取最后 |

## 7. 后续（T3-T5）

- ui_text 断言：`generate_assertions` 从 state_before≠after 生成；回放 `after_snapshot` 对比评估。
- 回放前后快照：runner 采同 schema 快照入 replay_run。
- E2E 盲区实测：njmind 改字段默认值 → ui_text 断言 FAIL（本 Sprint 核心价值证明）。
