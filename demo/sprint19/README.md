# Sprint 19 验收记录：流程生成 + 多站点实测 + 夜间开发一例（块 R + S18 T4）

日期：2026-09-25。分支 sprint19-flow-synthesis。主计划 v1.5 块 R。

## 验收结果

| # | 功能点 | 结果 | 真实证据 |
|---|---|---|---|
| R1 流程提案 | ✅ | 目标"在新浪搜索页搜索'大模型'"→ LLM 分解 3 步（goto/input/click），**每步证据背书回查通过**（页面/变量/锚点全部来自已学证据） |
| R2 流程执行 | ✅ | 3 步全 ok，status=executed（常驻窗口真实搜索"大模型"）；C1 门控（写锚点需 confirm）有测试 |
| R3 多站点 | ✅ | **网易**（导航流：锚点"国内"/"国际"+analytics API）+ **搜狐**（搜索流：`ExecuteSiteSearch` conf 0.6，锚点"站内搜索"+odin search API）——管道零改动兼容第 3/4 个站点 |
| S18 T4 夜间开发一例 | ✅ | 需求"请假表单增加紧急联系电话字段"→ LLM 结构化（add_field/文本输入框/jinjilianxidianhua）→ 回查 → 确认 → **浏览器自动执行**（加字段+权限+保存 code 200）→ 常驻浏览器验证字段真实存在（第 7 字段） |
| — | 三套测试 | ✅ | server **275**（262→275）|

## 实测抓出的真 bug（已修）

| # | Bug | 修复 |
|---|---|---|
| 1 | **空骨架 induce 幻觉命名**：网易两会话不同锚点（国内/国际）正确分桶但骨架为空 → LLM 对空 prompt 幻觉出 `PurchaseOrderApproval` | induce 空骨架短路：不调 LLM，直接 candidate+notes"骨架为空"（省 LLM 调用+防幻觉） |
| 2 | 搜狐 readonly 搜索框激活式交互：fill 未被采集为 input action（click 后才可编辑） | 记录为采集层发现（readonly 激活模式），不阻塞——click 流已可学习 |

## 产品里程碑

- **M3 完整出口达成**：夜间开发（G 块）+ 定向回归（F）+ 编排画布（H）+ 晨间评审（I）全链真跑通——"白天录需求，晚上 AI 开发+测试，第二天早上人 Review"的宪法北极星首次完整落地
- **流程生成**（块 R）：Evidence-backed Flow Synthesis——与 Katalon"需求直出脚本"的差异化实证：每步证据背书，非凭空生成
- **4 站点泛化**：njmind + 新浪 + 网易 + 搜狐，管道零改动

## Sprint 回顾（宪法 §12）

- #1 北极星闭环（夜间开发一例）✓；#8 LLM 边界：空骨架短路防幻觉（新实战案例）✓；C1 延伸门控（dev-plan confirm）✓；C3 execution_log/synth_flow 全落库 ✓
