# Sprint 12 学习深化 Implementation Plan（块 N）

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。先读 AGENTS.md。
> 派生自：主计划 v1.3 块 N。输入实证：S11 三边界（demo/sprint11/README.md N1 观察数据）。

**Goal:** 补全 v3 设想的学习能力缺口——新功能增量发现（边界①②）、Requirement 先验对齐、Outcome 层1 采集（边界③的信号侧）、层4/5 深化、Active Probing 设计评估。

**Architecture:** ①**N1 发现**：process 管道新增 discovery 步——会话的 API 模板集合与 evidence_edge 已知 dst 集合做差，新模板 + 新锚点 label 落 `discovered_feature` 表（session_id/api_template/anchor_label/observed_count/first_seen/last_seen/status: new|linked|dismissed；同模板重复出现累加计数）；LLM 仅命名（feature 猜名，可选 v1 先不做命名，纯确定性记录）。②**N2 先验对齐**：confirmed 的 expected_delta 的 changes（api_add/ui_action 值）与 discovered_feature 匹配（api 模板精确匹配 + ui_action 文本子串匹配）→ 更新 status=linked + 记录 delta_id；报告页显示"已发现对应实现"。③**N3 层1 toast 采集**：插件 snapshot 增加 `toasts` 字段（锚点后 2.5s 内可见的 n-message/[class*=message] 文本，≤3 条×100 字符，脱敏词表同 redact）；server signals 扩展——state_signals 提取时若窗口快照含 toasts，生成 `ui_toast` 信号（field="toast", value=文本）；outcome 生成 `toast_signal` 断言（kind 复用 state_signal，field="toast"）。④**N4 层4/5**：层4——outcome_assertion 已有 evidence_count；新增晋升规则：verify/replay 通过次数 ≥3 → payload 标 `layer4_verified: true`（历史成功样本背书）；层5——同 skill 多次 replay 的 assertion 观测值一致性检查端点（`GET /skills/{id}/consistency`：各断言历史观测值集合，全一致=true）。⑤**N5 设计文档**：docs/arch/active-probing-design.md（规则猜测→边界探测→C1 门控；标注 G6 闸口）。

**Tech Stack:** 1 迁移（discovered_feature 表）；插件 snapshot.ts 扩展；server process/signals/outcome 扩展。

## Global Constraints

- C3：discovery 决策落库可审计（audit 页后续接入，本 Sprint 先 API）。
- LLM 边界：N1 v1 纯确定性（不调 LLM 命名，避免为命名烧调用；命名留给后续 induce）。
- 测试基线：172/21/24；每任务全量绿；仪式全流程走完再合并。

---

### Task 1: N1 新功能增量发现（TDD + 迁移）
- 迁移：discovered_feature 表（id/session_id/api_template/anchor_label/observed_count default 1/first_seen/last_seen/status default "new"/linked_delta_id nullable）。
- process.py：process 后收集本会话全部 API 模板（semantic_action.api_calls）+ 锚点 labels；与 evidence_edge.dst 集合差分 → 新者 upsert discovered_feature（同 api_template 累加）；已知者跳过。
- 端点：GET /api/v1/discoveries（列表，status 过滤）。
- 测试：新 API 模板会话 → discovery 落库 status=new；同模板二次会话 → observed_count=2；全已知模板会话 → 无新行。

### Task 2: N2 Requirement 先验对齐（TDD）
- change/expected.py confirm 时：changes 中 api_add 值与 discovered_feature.api_template 精确匹配、ui_action 与 anchor_label 子串匹配 → status=linked, linked_delta_id 记录。
- 报告页（DeltaReport.vue）：需求上下文区显示"已发现实现"徽标（linked 的 discovery 计数）。
- 测试：造 discovery + confirm 匹配 delta → linked；不匹配 → 保持 new。

### Task 3: N3 Outcome 层1 toast 采集（TDD）
- 插件 snapshot.ts：collectSnapshot 增加 toasts 采集（document.querySelectorAll('.n-message,[class*=message]') 可见文本，锚点后快照含）；types.ts Snapshot 加 toasts?: string[]；脱敏复用 SENSITIVE_KEY_RE。
- server：schemas snapshot payload 透传；process 的 state_signals 提取扩展——窗口 after 快照 toasts → 生成 {api: anchor, field: "toast", value: 文本} 信号；outcome 生成断言（state_signal kind, field="toast"）。
- 测试：插件（jsdom toast DOM → toasts 采集+脱敏）+ server（含 toast 快照会话 → toast 信号+断言生成+回放评估）。

### Task 4: N4 层4/5（TDD）
- 层4：verify_against_session 与 replay 评估通过时 assertion.evidence_count += 1（现有 verify 是查询不改状态——改为累加需评估；简化：verify 端点通过时累加）；payload 加 layer4_verified 当 count≥3。
- 层5：GET /skills/{id}/consistency——聚合该 skill 全部 replay_run 的 assertion_results 历史 observed_status/observed value 集合，输出每断言 {values, consistent}。
- 测试：3 次 verify 通过 → layer4_verified；两次 replay 观测不同 → consistent=false。

### Task 5: N5 Active Probing 设计文档
- docs/arch/active-probing-design.md：观察→规则猜测（确定性阈值归纳）→边界探测计划→C1 门控执行→G6 闸口（可重置测试环境授权）。

### Task 6: 仪式收尾
- 全量三套 → 审查 → 文档（arch 契约 + README）→ 浏览器实测（discoveries 端点 curl + 报告页徽标截图）→ 用户测试报告 → 合并。
