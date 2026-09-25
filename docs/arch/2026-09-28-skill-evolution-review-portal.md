# S15 块 I：Skill 版本演化 + 评审门户（后端契约）

> 2026-09-28，分支 sprint15-review-evolution。对应计划：docs/superpowers/plans/2026-09-25-sprint15-review-evolution.md（Task 1/2）。
> 宪法依据：v3 §29「不能覆盖旧版本」；C3 评审决策落库可审计。

## I2 Skill 版本演化（语义变更）

### 数据模型（迁移 e5f7a3c1b9d2，head 链 c9e2f4a7b6d1 → e5f7a3c1b9d2）

- `skill.version` Integer，server_default 1；存量行迁移内回填 `UPDATE skill SET version=1 WHERE version IS NULL`。
- `skill.superseded_by` Integer nullable——指向**直接后继**版本（链式，不指向最新版）。
- `review` 表：id PK / agent_run_id Integer index / reviewer String(100) / decision String(20) / comment Text nullable / created_at。

### induce 语义（app/learning/skill.py induce_skill）

re-induce **不再删除**旧 skill（原"先删断言再删 skill"孤儿治理整体移除）：

- 旧行（同 alignment，且当前非 superseded）→ `status="superseded"` + `superseded_by=新行 id`；
- 新行 `version = 旧最大 version + 1`（首版 1）；
- 断言/策略只写新行；旧行的断言/策略**原样保留作历史**（superseded 行保留一切）。

### 端点行为

| 端点 | superseded 行为 |
|---|---|
| GET /api/v1/skills | 默认排除 |
| GET /api/v1/baseline/skills、/baseline/compare | 默认排除（compare 同口径，避免多版本重复计数） |
| GET /api/v1/audit/sessions/{sid}/trace | skills 段排除；replay_runs 段仍全量（C3 审计不丢历史） |
| GET /api/v1/skills/{id}/card | 200 + `superseded_by` 字段（活跃行为 null；前端提示用） |
| POST /api/v1/assertions/{id}/verify | 409 `该版本已被取代（v{新版本号}），请验证新版本` |

## I1 评审门户后端（app/api/reviews.py）

评审对象是**夜间运行 agent_run**（区别于四分类报告页 /reports/:deltaId——那看的是发版四分类）。

- `POST /api/v1/reviews {agent_run_id, reviewer, decision, comment?}`
  - decision Literal `approved|rejected|changes_requested`（非法值 422）；
  - agent_run 不存在 404；同 run 已评审 409；201 返回评审行 + agent_run 摘要。
- `GET /api/v1/reviews?decision=`：id 倒序列表，每项含 `agent_run: {graph_name, status, started_at}`；decision 查询参数同样枚举校验。
- `GET /api/v1/reviews/pending`：未评审 agent_run 队列（id 倒序），项为 `{id, graph_name, status, started_at, node_outputs}`——node_outputs 摘要透传，评审页据此渲染 review_output 段（画布流水线 n5 节点产物）。

## 测试

- 语义变更测试更新：test_skill.py 孤儿治理两测（旧行被删/旧断言 404）→ superseded 保留/verify 409/版本递增；test_cards_api.py card 字段集加 superseded_by。
- 新增：test_skill.py 版本链（v1→v2→v3）与列表过滤；test_reviews.py 6 例（创建/422/404/409/过滤/pending）。
- 基线 224 → 232 passed。
