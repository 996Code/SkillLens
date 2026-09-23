# Sprint 2 端到端验收记录（多演示对齐 + 变量识别）

日期：2026-09-24
环境：macOS + Chrome（extension/dist）+ uvicorn 8710 + SQLite
被学习系统：njmind / 明搭云-MingBuilder（表单设计器 field-edit 页）
演示 session：`426c3da9`（保存表单 v1，17 事件/8 窗口）+ `f007da25`（保存表单 v2，7 事件/3 窗口）
alignment_id：1

## 验收结论

| # | 检查项（计划 Task 7 Step 3） | 结果 | 证据 |
|---|------------------------------|------|------|
| 1 | 两 session process 出窗口且含保存窗口 | ✅ | v1 8 窗口、v2 3 窗口，均含 click:保存 |
| 2 | skeleton 非空且含保存步 | ✅ | 2 步：`click:请输入` → `click:保存`（GET getTableConfig + POST saveFormConfig + POST saveTableConfig） |
| 3 | param_variables 含跨次不同值（或以 input 为准） | ✅ | 两次保存同一表单配置 → formConfigId 相同非变量（计划已预判此情形）；以 input 为准 |
| 4 | input_variables 含两次不同的输入 | ✅ | `请输入` 字段：v1=`wenbenshurukuang2321`、v2=`jilian1111` |
| 5 | 录制中刷新页面事件不丢 | ⚠️ 部分 | 本轮两 session 各仅 1 个 page_id（用户未在录制中刷新），跨页修复由单测覆盖（test_same_seq_different_page_accepted），实机多页场景留日常使用观察 |
| 6 | GET /alignments/{id} 回读 | ✅ | 回读一致 |

核心成果：**两次不同操作路径归并为同一流程骨架 + 输入值被识别为变量**——Skill 归纳的直接前置物就绪（spec §7 Sprint 2 验收达成）。

## 本 Sprint 修复的终审必修项

1. **必修①（C3 形式补全）**：`normalized_event`/`transaction_window` 中间表落库，窗口行内含 `idle_ms=2000`/`max_window_ms=8000` 参数快照。
2. **必修②（跨页 409 丢批）**：事件级 `page_id` + 复合唯一约束 `(session_id, page_id, seq)`；同页同 seq 仍 409（幂等保持）。

## 过程记录

- 重载插件瞬间的 `Extension context invalidated` 为预期现象（孤儿脚本周期任务），不影响采集；popup 自检提示与孤儿静默化列 Sprint 3。
- 迁移链：cac56092f499 → 24574ffda624（raw_event 表重建）→ 2de33db18300（中间表）→ 044494e885c6（alignment）。

## 复现步骤

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
cd extension && npm run build   # Chrome 加载 dist + 刷新页面
# 两次演示（不同输入值），然后：
S1/S2 = 两个 session id
curl -s -X POST .../sessions/$S1/process && curl -s -X POST .../sessions/$S2/process
curl -s -X POST .../align -d '{"session_ids": ["$S1","$S2"]}' | python3 -m json.tool
```
