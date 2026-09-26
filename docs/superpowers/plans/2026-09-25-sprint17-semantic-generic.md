# Sprint 17 语义定位强化 + 通用能力层 Implementation Plan（块 L 启动）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 依据：SWOT P0/P1（docs/reviews/2026-09-25-swot-iteration.md）+ 主计划块 L。G5 已满足（njmind 表单流 + 新浪搜索流 = 2 任务族）。

**Goal:** ①语义定位强化（块 P 发现 W1：采集侧跳过框架自动生成 id）②块 L 通用能力层落地（generic_skill 模型/归纳/晋升纪律/槽位映射/迁移实测）。

**Architecture:** ①**T1 语义定位**：插件 input-key.ts 回退链跳过框架自动生成 id（`rc_select_\d+`/`rc_input_\d+`/`ant-`前缀/纯数字 id），无语义时 label 留空（回放侧 locate 已有 #id 兜底，但采集侧不该把不稳定 id 当语义）。②**T2 generic_skill 表**：id/name/description/slots_schema JSON（槽位定义）/status candidate|learned/source_skill_ids JSON/evidence_refs JSON/created_at。③**T3 归纳端点**：POST /generic-skills/induce {skill_ids}——LLM 从多个系统绑定 Skill 提议通用模板（name/slots_schema），**确定性回查**：模板引用的每个槽位值必须能在源 skill 的骨架/变量中找到对应；回查不过→candidate。④**T4 晋升纪律**：绑定 ≥2 个不同系统（skill 的 alignment session 的 target_system 不同——现无此字段，用 skill 骨架 API 前缀区分：njmind=/codeBack、新浪=/api）且各源 skill 回放 PASS → learned。⑤**T5 槽位映射+迁移实测**：POST /generic-skills/{id}/map {target_skill_id}——通用模板槽位与具体 skill 的变量/锚点对齐校验（确定性）；真库用 njmind 保存流+新浪搜索流归纳出"FillAndSubmit"类通用 Skill，验证双系统绑定晋升 learned。

**Tech Stack:** 1 迁移（generic_skill 表）；插件 input-key.ts；LLM 归纳 1 次调用（宪法边界内：结构化）。

## Global Constraints

- LLM 边界：归纳只产出 name/slots_schema 结构；回查/晋升/映射全确定性。
- C3：generic_skill 全字段落库；归纳的 LLM 调用落 llm_call_log。
- 测试基线：232/27/34；仪式全流程（浏览器实测+UI 评估记录）。
- 系统区分 v1：骨架 API 模板前缀（/codeBack=njmind，/api=新浪）——target_system 字段化列入后续。

---

### Task 1: 语义定位强化（插件，TDD）
- input-key.ts：回退链（name→id→placeholder→aria-label）中 id 环节跳过框架自动生成模式（`/^(rc_|ant-|__|mui-|:r\d)/` 或纯数字）；跳过后继续链；全空→label 空串。
- 测试：rc_select_0 被跳过（落到 placeholder）；正常 id 仍用。

### Task 2: generic_skill 表 + 模型（TDD + 迁移）
- 迁移：generic_skill 表。
- models.py：GenericSkill。

### Task 3: 归纳端点（TDD）
- POST /api/v1/generic-skills/induce {skill_ids: list[int]}（≥2 校验）：
  - 取各 skill（含骨架/变量/断言摘要）→ LLM prompt（真实 LLM）提议 {name, description, slots_schema: [{slot, description, example_from_skill_N}]}
  - **确定性回查**：slots_schema 每个槽位的 example 必须能在对应源 skill 的骨架签名/变量名/断言 payload 中找到（子串匹配）；回查失败→status=candidate + notes 记原因
  - 落库（source_skill_ids/evidence_refs=各源证据引用）
- GET /api/v1/generic-skills（列表）/ GET /{id}。

### Task 4: 晋升纪律 + 槽位映射（TDD）
- 晋升：POST /generic-skills/{id}/promote——校验：源 skill 覆盖 ≥2 个系统（API 前缀区分）且各源 skill 最近回放 PASS → learned；否则 409 带原因。
- 映射：POST /generic-skills/{id}/map {target_skill_id}——校验目标 skill 的骨架/变量能填满 slots_schema 的每个槽位（确定性子串/结构匹配）→ 返回 {mapping: {slot: 目标值}}；填不满→409 列缺口。

### Task 5: 真库迁移实测 + 仪式收尾
- 真库：njmind skill（SaveFormAndTableConfig）+ 新浪 skill（ExecuteSearch）→ induce → 回查 → promote（双系统+双 PASS）→ map 校验。
- 浏览器实测：工作台加通用 Skill 区块（SkillsList 页脚或独立区——最小：列表页底部显示 generic-skills 摘要行）+ 截图；**UI 评估记录**（对照 S16 新 UI，记录需优化项）。
- 全量三套 → 审查 → 文档 → 合并。
