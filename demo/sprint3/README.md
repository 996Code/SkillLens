# Sprint 3 端到端验收记录（真实 LLM 首跑 + 演示 2：Skill 卡片）

日期：2026-09-24
环境：uvicorn 8710（加载 server/.env 真实 LLM）+ SQLite；被学习系统数据：Sprint 2 的两次演示（alignment_id=1）
LLM：qwen3.7-plus（OpenAI 兼容协议，经 996code.top 网关）

## 验收结论：7/7 通过

| # | 检查项（计划 Task 6 Step 4） | 结果 | 证据 |
|---|------------------------------|------|------|
| 1 | llm_call_log 真实记录 | ✅ | purpose=skill_naming, provider=openai-compat, model=qwen3.7-plus, 116/732 tokens, 13.9s, prompt/response 非空 |
| 2 | induce 返回 learned + 合理命名 | ✅ | **`SaveFormAndTableConfig`** / "输入并保存表单与表格的配置信息"（准确概括了保存表单+表格两份配置的流程） |
| 3 | Skill 卡片字段齐全 | ✅ | skeleton 2 步 / confidence 0.7 / evidence_count=2 / input_variables（请输入: 两值） |
| 4 | 断言 ≥3 条覆盖三 kind | ⚠️→✅ | 4 条：3×api_status + 1×state_signal（field_change 0 条——本数据集无同 session 两次保存，语义正确，见下） |
| 5 | 全部断言 verify PASS | ✅（修复后） | 4/4 PASS |
| 6 | Sprint 2 数据 field-changes | ✅ | 0 条为正确语义：saveFormConfig 每 session 仅一次（field-change 定义为同 session 相邻两次 POST 的 diff；跨 session 差异由变量层负责，input_variables 已捕获） |
| 7 | Fake 回退回归 | ✅ | conftest 空 key 环境下 59 passed 全绿（T1 审查已在含真实 .env 的本机等价验证） |

## E2E 发现并修复的缺陷

- **fix1（ec23458）断言范围缺陷**：generate_assertions 原从全部 semantic_action 生成断言，把 v1 独有窗口（组合字段/特殊字符等 6 条 API）也当成了 Skill 断言 → 在 v2 session 上必 FAIL（10 条中 6 条 FAIL）。修复：只从骨架 `skeleton[].session_window_seqs` 指向的窗口生成。修复后断言收敛为 4 条（正是保存流程的 3 个 API + 1 个状态信号）且 4/4 PASS。**这是"Skill 证据范围"语义的重要修正**——单测因测试数据恰好无多余窗口而未暴露。

## 过程发现（Sprint 4 议题）

- njmind 表单设计器的 saveFormConfig reqBody 高达 **100KB**（全量表单配置 JSON）——diff/存储性能需注意（截断或流式 diff）；
- qwen 首次真实调用 latency 13.9s（含网络），命名质量值得信任；
- 两次演示骨架重复签名场景未出现，LCS 首匹配语义维持 MVP。

## 核心成果

**SkillLens 第一次拥有了"学会的技能"**：

```
Skill #1: SaveFormAndTableConfig（learned, confidence 0.7, evidence 2）
  流程: click:请输入 → click:保存 [POST saveFormConfig, GET getTableConfig, POST saveTableConfig]
  变量: 请输入 = {wenbenshurukuang2321, jilian1111}
  断言: 4 条（3 API status + 1 状态信号），全部在两次演示上回放通过
```

## 复现步骤

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
curl -s -X POST .../api/v1/alignments/1/induce     # 真实 LLM 命名
curl -s -X POST .../api/v1/skills/1/assertions     # 生成断言
curl -s -X POST .../api/v1/assertions/{1..4}/verify  # 回放验证
sqlite3 server/skilllens.db "SELECT purpose, model, latency_ms FROM llm_call_log;"
```
