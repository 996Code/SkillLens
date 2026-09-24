# Sprint 7 技术债清障 + 演示基线固化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 2 真实流量进来之前，清掉已知技术债（LLM 调用失败零记录、re-induce 断言孤儿 500、100KB reqBody diff 性能、align 与 transaction_window 错位），并把刻意演示的基线指标固化成可对比数据——为 C2 的"真实流量置信度 ≥ 演示基线 80%"提供测量锚点。

**Architecture:** ①`llm/gateway.complete()` 包 try/except，异常时落一条 status=error 的 llm_call_log（prompt 保留、response 记异常摘要、token 记 NULL）后 re-raise——C3 的失败路径补全；②`induce_skill` 删 Skill 前先删其 outcome_assertions（孤儿根治）+ re-induce 后旧断言 verify 返回 404 而非 500；③`ingestion/fielddiff.py` 对 >8KB 的 reqBody 截断哈希后 diff（存摘要+哈希，全文不入库）；④`ingestion/alignment.py` 的 window_signature 与 windows.py 切窗参数快照对齐（idle_ms/max_window_ms 记录进 alignment 元数据）。基线固化：新增 `GET /api/v1/baseline/skill/{id}` 返回指标 JSON + `scripts/baseline_snapshot.py` 导出。

**Tech Stack:** 无新依赖；SQLite json_set/json_extract；pytest monkeypatch。

**Spec:** `docs/specs/2026-09-23-skilllens-mvp-design.md` §0.3 Phase 2 出口标准（置信度对比锚点）、C3（全链路持久化——含失败调用）、§8 风险表。

## Global Constraints

- **C1/C2/C3 沿用**：影子门控零改动；本 Sprint 全部是 server 端，不碰插件协议。
- **安全红线**：llm_call_log 落库的 prompt 已含业务数据（设计内）；异常摘要只记 `type(e).__name__ + str(e)[:200]`，不得含响应体（可能带网关回显的 key 片段——实测 new-api 401 body 无 key，但按红线从紧）。
- **测试基线：pytest 102**（2026-09-24 Windows 适配后）；每任务全量通过。
- **测试即规格**：brief 与测试矛盾时以测试为准最小修正并记录。
- 合并选项：本地合 main + 删分支 + 清工作区。

---

### Task 1: complete() 异常落库（TDD）

**Files:**
- Modify: `server/app/llm/gateway.py`
- Test: `server/tests/test_gateway.py`（追加）

**Interfaces:**
- Consumes: 现有 `complete(db, purpose, prompt)`。
- Produces: 异常时先 `db.add(LlmCallLog(purpose, provider=provider.name, model, prompt, response=f"{type}:{msg[:200]}", prompt_tokens=None, completion_tokens=None, latency_ms))` + commit，再 raise。

- [ ] **Step 1: 写失败测试**

```python
def test_complete_logs_on_provider_error(client, monkeypatch):
    from app import llm_gateway
    class Exploding:
        name = "openai-compat"
        def complete(self, prompt):
            raise RuntimeError("boom-connection")
    monkeypatch.setattr(llm_gateway, "get_provider", lambda: Exploding())
    from app.db import SessionLocal
    from app.models import LlmCallLog
    db = SessionLocal()
    from sqlalchemy import select
    try:
        with pytest.raises(RuntimeError):
            llm_gateway.complete(db, "skill_naming", "p")
        row = db.execute(select(LlmCallLog).order_by(LlmCallLog.id.desc())).scalars().first()
        assert row.purpose == "skill_naming"
        assert "RuntimeError" in row.response and "boom" in row.response
        assert row.prompt_tokens is None and row.latency_ms >= 0
    finally:
        db.close()
```

- [ ] **Step 2: 红** → `cd server && uv run pytest tests/test_gateway.py -q`
- [ ] **Step 3: 实现** gateway.complete 包 try/except（异常落库后 re-raise）
- [ ] **Step 4: 绿 + 全量** `uv run pytest -q`（103 passed）

### Task 2: re-induce 断言孤儿根治（TDD）

**Files:**
- Modify: `server/app/learning/skill.py:71`（delete 前清孤儿）
- Modify: `server/app/api/llm_skills.py:69-72`（verify 的 skill 消失返回 404）
- Test: `server/tests/test_skill.py`（追加）

**Interfaces:**
- Produces: `induce_skill` 删旧 Skill 前执行 `db.query(OutcomeAssertion).filter(skill_id in 旧ids).delete()`；`verify_assertion` 对 skill 缺失 raise HTTPException(404)。

- [ ] **Step 1: 写失败测试**（诱导→断言→再诱导→旧断言 id verify 应 404 且不 500；断言行已删除）
- [ ] **Step 2: 红**
- [ ] **Step 3: 实现**（两处小改）
- [ ] **Step 4: 绿 + 全量**（104+ passed）

### Task 3: 100KB reqBody 截断保护（TDD）

**Files:**
- Modify: `server/app/ingestion/fielddiff.py`
- Test: `server/tests/test_fielddiff.py`（追加）

**Interfaces:**
- Produces: reqBody 超过 8192 字节时：截断至 8192 + 记 `payload["truncated"]=true` + 全文 sha256 存 `payload["sha256"]`；diff 在截断文本上做（njmind 100KB 场景实测可接受降级——字段默认值本就不在 reqBody，这是 Sprint 8 UI 快照的依据）。

- [ ] **Step 1: 失败测试**（构造两个 10KB reqBody → field_changes 落库行带 truncated=true 且 sha256 长度 64）
- [ ] **Step 2: 红 → Step 3: 实现 → Step 4: 绿 + 全量**

### Task 4: align 元数据补窗口参数快照（TDD）

**Files:**
- Modify: `server/app/ingestion/alignment.py`（align 结果附 `window_params`）
- Test: `server/tests/test_alignment.py`（追加）

**Interfaces:**
- Produces: alignment 行新增 JSON 字段 `window_params`（从两 session 的 transaction_window 行读 `idle_ms/max_window_ms` 快照，不一致时记两个值并加 warn 标记）——错位可追溯，参数化调整时对账用。

- [ ] **Step 1-4: 同 TDD 循环**（Alembic 迁移 `add window_params to alignment`）

### Task 5: 演示基线固化

**Files:**
- New: `server/app/api/baseline.py`（GET /api/v1/baseline/skills）
- New: `scripts/baseline_snapshot.py`（导出 JSON 到 demo/baseline/）
- Test: `server/tests/test_baseline_api.py`

**Interfaces:**
- Produces: 每个 learned skill 输出 `{skill_id, name, confidence, evidence_count, assertion_count, assertion_pass_rate, input_var_names, window_params}`；snapshot 脚本聚合导出——**这就是 C2 的 80% 对比锚**。

- [ ] **Step 1-4: TDD 循环**（先红：接口 404）
- [ ] **Step 5: 实跑导出**（真实 LLM 环境跑一轮 auto_record→pipeline→snapshot，产物入 `demo/baseline/2026-09-24-baseline.json`）
- [ ] **Step 6: 全量回归**（105+ passed）

### Task 6: E2E 验收 + 回顾

- [ ] **Step 1: 真实环境验收**：错误 key 场景 induce → llm_call_log 有 error 行且 API 返回 500（非静默）；re-induce → 旧断言 404；10KB body 会话 → truncated 标记；baseline snapshot 产出。
- [ ] **Step 2: 全量 pytest + extension 测试（Node 24 PATH）**
- [ ] **Step 3: lessons 补记**（如有新坑）
- [ ] **Step 4: 合并 main**（本地 merge + 删分支 + 清工作区）
