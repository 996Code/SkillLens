# Sprint 24：块 U 自愈与维护闭环

> 主计划 v1.6 块 U。对标 Testim/Mabl self-healing + QA Wolf AI 维护代理。
> 宪法边界：LLM 只提案，确定性验证（locate 实测）后才生效；C1 纪律贯穿。
> 用户要求：多维度、多角度测试（本计划专设测试矩阵）。
> TDD 先红后绿；完成后走阶段闸门仪式。

## 设计决策

### U2 flaky 重跑（先做，独立）
- 配置 `REPLAY_FLAKY_RERUN`（默认 1=开）：execute 回放 status=fail 时同浏览器重试一次。
- 重试通过 → 最终 run status=pass + `flaky` 列=True + `plan["first_attempt"]`
  嵌入首次失败明细（C3：失败尝试可审计，不丢）；重试仍 fail → 保持 fail 不标 flaky。
- `_execute_skill` 重构：抽出 `_attempt()`（无 DB 写），主函数编排两次尝试。
- 一致性端点响应加 `flaky_runs` 计数；卡片 last_run 带 flaky；前端徽标。

### U1 定位修复提案
- 表 `locate_proposal`：skill_id/step_label/proposed_label/strategy/
  status(proposed|verified|promoted|rejected)/verify_count/source_run_id/created_at。
- 生成（回放中，页面还开着）：步骤定位失败 → 采页面快照 → LLM（purpose=
  locate_repair）从可见元素中提议新标签 → **确定性验证**：locate(page, 提案)
  实测命中且可见 → verified；不命中 → 停留 proposed（永不参与回放）。
- 回放自愈：execute_plan 前加载该 skill 的 verified/promoted 提案 →
  click/input 定位失败时按提案重试；成功记 repair_proposal_id，run 落库后
  verify_count++；verify_count ≥ `LOCATE_AUTO_PROMOTE_N`（默认 3）→ 自动晋升 promoted。
- 人工否决：POST /locate-proposals/{id}/reject（reviewer/admin）→ rejected 不再参与。
- 去重：同 skill+step_label 已有 verified/promoted 提案时不重复生成。

### U3 归因→修复闭环
- 提案带 source_run_id → 列表端点 join replay_run.attribution → 前端展示
  "失败→归因→提案→验证"链（源 run 归因摘要 + 验证次数 + 状态）。

## 多维度测试矩阵（用户要求）

| 维度 | 覆盖 |
|---|---|
| 单元 | flaky 判定纯逻辑、提案状态机、fallback map 构造 |
| 集成（真实浏览器+状态化页面） | 按钮改名→定位失败→提案生成+验证→再回放自愈通过→N 次后自动晋升 |
| 状态化页面 | 首次 500 二次 200 → run1 fail→重试 pass→flaky=True；关配置→保持 fail |
| 负例/边界 | LLM 提案不存在的标签→停留 proposed 不参与回放；rejected 提案不参与；重试仍失败不标 flaky |
| 角色权限 | reject：viewer 403 / reviewer 200 |
| 前端 | 提案区块渲染（状态徽标/归因摘要/否决按钮）、flaky 徽标 |
| 回归 | 存量 325 全绿（execute_plan 加默认参数零破坏） |

## 任务

- T1 U2 flaky 重跑（重构 _attempt + flaky 列迁移 + 一致性/卡片/前端）
- T2 U1 提案表+迁移+生成（回放内 LLM+确定性验证）
- T3 U1 回放自愈（fallback 重试+计数+自动晋升）+ reject API
- T4 U3 提案列表 API（含归因）+ 前端自愈提案区块
- T5 收尾：三套全绿 + 浏览器实测 + 截图 demo/sprint24/ + 用户测试报告 + 文档 + 合并

## 验收标准（对照主计划块 U）

- [ ] U1 定位失败→LLM 修复提案→影子验证通过才生效；人工 confirm 或 N 次通过自动晋升
- [ ] U2 回放失败自动重跑 1 次（配置化），两次结果不一致标记 flaky 进一致性统计
- [ ] U3 归因结果与修复提案关联，"失败→归因→修复→验证"链路可视化
