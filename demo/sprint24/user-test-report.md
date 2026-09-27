# Sprint 24 用户测试报告：块 U 自愈与维护闭环

> 日期：2026-09-27 · 分支：s24-self-healing · 计划：docs/superpowers/plans/2026-09-27-sprint24-self-healing.md
> 目标：对标 Testim/Mabl self-healing + QA Wolf AI 维护代理。宪法边界：LLM 只提案，
> 确定性验证（locate 实测）后才生效。用户要求多维度测试——本报告按矩阵逐项对照。

## 一、多维度测试矩阵结果（用户要求逐项）

| 维度 | 用例 | 结果 |
|---|---|---|
| **单元/集成（真实浏览器）** | 按钮改名（保存→提交表单）→ 定位失败 → LLM 提案 → locate 实测 verified → 再回放 click 经 repair 成功 → run pass → verify_count=1 | ✓ test_locate_repair_full_cycle |
| **状态化页面** | 首次 500 二次 200 → run1 fail → 自动重试 pass → flaky=True + plan.first_attempt 嵌入失败明细；关配置（REPLAY_FLAKY_RERUN=0）→ 不重试保持 fail | ✓ test_flaky_rerun ×3 |
| **负例/边界** | LLM 提案不存在的标签 → 停留 proposed 不参与回放（再回放仍失败）；重试仍失败不标 flaky | ✓ |
| **人工否决** | rejected 提案不参与自愈（再回放仍失败） | ✓ |
| **角色权限** | reject：viewer 403 / reviewer-admin 200；前端 viewer 无否决按钮 | ✓ 后端+vitest+浏览器三层 |
| **自动晋升** | LOCATE_AUTO_PROMOTE_N=1 时使用一次即晋升 promoted；默认 N=3 | ✓ |
| **U3 归因链** | 提案列表含源 run 归因文本；浏览器实测显示 run #59 真实归因（"视觉基线断言不通过…9.3%"） | ✓ API+浏览器 |
| **数据出口** | flaky 进卡片（last_run.flaky）与一致性统计（flaky_runs 计数） | ✓ |
| **前端** | 提案区块（原标签→提案标签/状态徽标/验证次数/归因摘要/否决按钮）、flaky 徽标、无提案隐藏 | ✓ vitest ×3 |
| **回归** | 存量 325 全绿（runner 重构 _attempt 抽取零破坏；execute_plan 加默认参数零破坏） | ✓ 334 passed |

### 三套测试

| 套件 | 结果 |
|---|---|
| server pytest | **334 passed**（325+9：flaky 4 + repair 5） |
| web vitest | **48 passed**（45+3：proposal.spec.ts） |
| extension | **31 passed** |

## 二、设计要点（审查结论）

- **LLM 边界**：提案生成 purpose=locate_repair（C3 落 llm_call_log）；提案必须过 locate 实测
  （确定性）才 verified；proposed 状态永不参与回放 ✓
- **flaky 与自愈分离**：flaky 重试沿用同一 repair_map——本次新生成的提案留给下一轮回放，
  自愈是跨回放的，不与 flaky（真实非确定性）混淆 ✓
- **C3 审计**：flaky 首次失败明细嵌入 plan.first_attempt（不丢失败尝试）；提案带 source_run_id ✓
- **runner 重构风险控制**：_attempt 抽取后回放回归组 18 用例先行验证，再全量 334 ✓
- **去重**：同 skill+step_label 已有活跃提案（却仍失败）不重复生成（提案已失效场景留给人工）✓
- diff 敏感串扫描：无泄露 ✓

## 三、易用性发现

| 级别 | 发现 | 处置 |
|---|---|---|
| P2 | 提案晋升后不回写 skill 骨架（skeleton 仍存旧标签，靠提案库兜底） | 转后续需求：用 S15 supersede 机制生成新版本 skill（记录在案） |
| P3 | 提案无"人工确认提前晋升"按钮（只有自动晋升+否决） | 可接受——自动晋升 N 可调 |
| P3 | flaky 徽标只在详情页最近回放区 | 可接受 |

## 四、截图

- `screenshots/01-proposal-section.png`：自愈提案区块（promoted 徽标+归因链+否决按钮，admin）
- `screenshots/02-viewer-no-reject.png`：viewer 角色无否决按钮

## 五、验收标准对照（主计划块 U）

- [x] U1 定位失败→LLM 修复提案→确定性验证通过才生效；N 次通过自动晋升（人工可否决）
- [x] U2 回放失败自动重跑 1 次（REPLAY_FLAKY_RERUN 配置化），结果不一致标记 flaky 进一致性统计
- [x] U3 归因与提案关联（source_run_id），"失败→归因→修复→验证"链路在详情页可视化
