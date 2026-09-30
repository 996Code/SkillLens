# S43：自愈加固 + 图基座第二步 + 字段类型 LLM 归因

> 2026-09-30。三个块：①自愈晋升守卫（S43-1）②图基座第二步（S43-2）
> ③字段类型 LLM 归因层 3（S43-3）。

## S43-1 自愈系统缺陷修复（晋升守卫）

**缺陷实证**：状态依赖失败（前置条件不满足，如无激活 Bug 时"解决"
定位失败）→ LLM 从空状态页面选出无关元素（"搜索"）且 locate 验证
通过（页面上确实存在）→ 失败运行反复计数 verify_count → 晋升 →
骨架被打补丁污染（#111 被 #113 误取代，已手工撤销）。

**修复**（runner.py）：`record_usage` 只在 run 整体 `status == "pass"`
时计数——修复后的步骤 ok 但断言未过 ≠ 自愈成功。

```python
if attempt["repair_used_ids"] and status == "pass":
    record_usage(db, attempt["repair_used_ids"])
```

## S43-2 图基座第二步（S39 后续清单落地）

| 能力 | 端点 | 说明 |
|---|---|---|
| 状态机归纳 | GET /skills/{id}/state-machine | 骨架步 state_signals 按 field 分流聚转移边（计数）；初始=无入边、终态=无出边。SkillGraphView 图下新区块 |
| 学习图 | GET /learning-graph + /graph/learning | session→window→semantic→align→skill 五层 trace 图化（最近 30 会话）；左树"测试活动"组入口 |
| 画布子图 | GET /canvas/{id}/flow | replay_batch 展开子技能（sub_of 标注；params/config 双兼容）；总览流水线卡片"批量测试"可点开子技能清单（图内下钻） |

真机验证：学习图 124 节点（30 session/40 semantic/12 align/12 skill）；
状态机区块上屏；批量测试点开子图（PartnerQuickCreate/CustomerCreationWorkflow）。

## S43-3 字段类型 LLM 归因（层 3）

分层：L1 builtin 关键词规则（原有）→ L2 learned 自愈反哺（原有）→
**L3 LLM 归因**（新）：

- `llm_attribute_type(db, label)`：规则不命中时 LLM 分类，输出必须
  严格落在类型枚举（phone/email/id_card/url/date/int/password）内才
  落库（source=llm, success_count=0）；垃圾输出不进知识库。
- 宪法约束保持：LLM 只做分类归因；值生成/校验仍走确定性规则。
- runner 接线（`_heal_with_llm_attribution`）：规则自愈零命中 →
  对**校验错误文本提到的字段**（确定性关联）做 LLM 归因 → 再走一次
  确定性生成。归因范围收窄的原因：自由文本字段（"备注"）不因 LLM
  误归因被破坏性换值（实测教训）。
- Web 字段类型页 llm 徽标（badge-info）。

## 测试

- test_locate_repair.py：失败运行不计数/不晋升，pass 后计数晋升（6 passed）
- test_flow_graph2.py：三个 builder + 三个端点（6 passed）
- test_field_types.py：LLM 归因三态 + 自愈接线（10 passed）
