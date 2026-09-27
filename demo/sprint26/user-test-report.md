# Sprint 26 用户测试报告：自愈晋升回写 skill 骨架（S24 遗留 P2 收口）

> 日期：2026-09-28 · 分支：s26-heal-supersede · 主计划 v1.6.1
> 目标：自愈闭环最后一环——提案晋升不再只靠提案库兜底，而是经 S15 supersede
> 机制生成 skill 新版本（骨架 healed），旧版本保留可审计。

## 一、多维度测试矩阵

| 维度 | 用例 | 结果 |
|---|---|---|
| **单元** | 骨架步 healed label 优先于录制 anchor label（compile_skeleton_plan） | ✓ |
| **集成（真实浏览器）** | 改名→提案→自愈（N=1）→**自动晋升生成 v2**：骨架 healed、断言复制、旧版 superseded、提案 applied_skill_id 记录 | ✓ |
| **闭环证明** | **新版本回放无需提案直接 pass**（click 无 repair_proposal_id，label=healed）——自愈真正"固化"进 skill | ✓ |
| **版本语义** | 旧版本回放 → 409 superseded（S15 语义复用） | ✓ |
| **人工路径** | POST /locate-proposals/{id}/promote：reviewer 200 提前晋升生成版本；viewer 403 | ✓ |
| **回归** | heal/repair/skill/replay 组 36 用例先行 → 全量 351 绿 | ✓ |

### 三套测试

| 套件 | 结果 |
|---|---|
| server pytest | **351 passed**（348+3） |
| web vitest | **50 passed**（提案区块加"→ v#id"版本标注，类型同步） |
| extension | **31 passed** |

## 二、设计要点（审查结论）

- **版本语义复用 S15**：新版本=活跃行拷贝（version+1、superseded_by 链式指向），
  与 re-induce 完全同构；旧版本断言保留作历史（v3 §29 不覆盖）✓
- **healed label 落点**：骨架步加 `label` 覆盖字段，compile_skeleton_plan 优先取——
  录制事件不动（证据不可变），修复显式落在 skill 版本上（可审计）✓
- **匹配规则**：签名锚点 `type:label` 精确匹配 step_label → 打 healed 标记 ✓
- **幂等**：已 promoted 的提案重复 promote 不重复生成版本 ✓
- diff 敏感串扫描：无泄露 ✓

## 三、截图

浏览器层 UI 渲染由 vitest 覆盖（提案区块"→ v#id"版本标注）；真实浏览器闭环由
集成测试（真实 Playwright 页面改名场景）覆盖。

## 四、验收对照

- [x] 自动晋升（N 次）→ supersede 生成新版本（骨架 healed + 断言复制）
- [x] 人工 promote 端点（reviewer/admin）提前晋升
- [x] 新版本回放无需提案兜底（自愈固化）；旧版本 409 可审计保留
