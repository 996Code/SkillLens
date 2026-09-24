# Sprint 10 真实流量切换 Implementation Plan（M2-块D）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 派生自：`docs/specs/2026-09-24-master-delivery-plan.md` 块 D（D1-D5）。G1 已解：目标系统 = 192.168.99.22（明搭云）。

**Goal:** C2 生效——Skill 归纳输入从"刻意演示"切到"真实用户流量"，配套噪声过滤与多路径分桶，达成"真实流量归纳置信度 ≥ 演示基线 80%"的测量闭环。

**Architecture:** ①**流量标记**：recording_session 加 `source` 字段（demo | real_traffic），popup 开录与 auto_record 分别标记（API 兼容：缺省 demo，语义对齐 C2 的"Phase 1 输入已明确标记"检查项）；②**噪声过滤**：ingestion 新增 `noise_filter.py`——窗口序列级启发式（纯浏览无写操作序列、单事件窗口占比、时长超长窗口、空锚点 label），落库 `filtered_window` 表（不删数据，C3 可审计可回放重过滤）；③**多路径分桶**：alignment 升级——同任务多策略先按骨架签名相似度分桶再桶内对齐，`skill_strategy` 表落地（spec §5 定义未实现项）；④**evidence_edge 基础表**：process/align 时从骨架步生成边（action→api→state），带 evidence_count；⑤**对比测量**：baseline 端点扩展 `source` 维度，真实流量 skill 与 demo 基线（demo/baseline/2026-09-24-baseline.json）对比出报告。

**Tech Stack:** 无新依赖；2 个 Alembic 迁移（session.source、filtered_window/skill_strategy/evidence_edge 三表）；插件改动最小（popup 上报 source=real_traffic 标记）。

**Spec:** 宪法 C2（"噪声处理是 Phase 2 的核心工作，不是可选项"）、§5 数据模型、主计划块 D。

## Global Constraints

- **C2 铁律**：本 Sprint 起真实归纳输入必须来自 real_traffic 会话；demo 会话仅作基线对照。
- **C3**：过滤决策落库（filtered_window），不物理删除任何 raw 数据——"可回放重过滤"。
- **C1**：不新增执行面；evidence_edge 只读派生。
- 测试基线：138（server）+12（web）+24（extension）；每任务全量绿。
- 真实流量采集期（T5）用户在旁：常驻窗口可见操作（用户自己日常用明搭云，插件后台录）。
- 每阶段完成走闸门仪式：三套测试→审查(耦合)→文档→浏览器用户测试(截图)→合并。

---

### Task 1: 会话流量标记（TDD + 迁移）

**Files:**
- Modify: `server/app/models.py`（RecordingSession 加 `source: str = "demo"`）
- New: 迁移（add column source，server_default demo）
- Modify: `server/app/api/events.py`（POST /sessions 接受 `source` 字段，枚举校验 demo|real_traffic）
- Modify: `extension/src/background/session.ts`（创建会话时带 source=real_traffic——popup 用户录制即真实流量）
- Test: `server/tests/test_sessions.py` 追加

**Interfaces:**
- Produces: 会话级来源标记；auto_record.py 显式传 demo（改 scripts/auto_record.py 的 START_RECORDING 消息加 source:"demo"）；旧数据缺省 demo。

- [ ] Step 1: 红——POST /sessions {"source":"real_traffic"} 回读该值；非法值 422；缺省 demo。
- [ ] Step 2: 实现 + 迁移（手写）+ 实跑。
- [ ] Step 3: 绿 + 全量；extension session.ts 改动 + 既有测试不破。

### Task 2: 噪声过滤（TDD + 迁移）

**Files:**
- New: `server/app/ingestion/noise_filter.py`（`classify_windows(session_windows) -> list[dict]`：每窗 {window_seq, kept, reason}）
- New: 迁移（filtered_window 表：session_id/window_seq/reason/created_at）
- Modify: `server/app/ingestion/process.py`（process 时先过滤，kept=False 窗不进 semantic_action 但落 filtered_window）
- Test: `server/tests/test_noise_filter.py`

**Interfaces:**
- 规则（v1 启发式，全部可配置常量）：①纯读窗口（无 POST/PUT/DELETE 且无状态信号）→ filtered "read_only"；②单成员窗口（仅锚点无后续事件）→ filtered "orphan_click"；③窗口时长 > max_window_ms×2 → filtered "overlong"；④锚点 label 为空/纯符号 → filtered "empty_label"。
- Produces: GET /sessions/{sid}/filtered-windows 端点（审计用）。

- [ ] Step 1: 红——四规则各一用例 + 保留用例（正常写窗口 kept=true）+ 落库断言。
- [ ] Step 2: 实现（纯函数 + process 挂接 + 迁移）。
- [ ] Step 3: 绿 + 全量；历史会话重 process 验证不误杀（既有 fixture 会话全 kept）。

### Task 3: 多路径分桶 + skill_strategy（TDD + 迁移）

**Files:**
- New: 迁移（skill_strategy 表：skill_id/strategy_signature/skeleton/window_seqs/evidence_count）
- Modify: `server/app/ingestion/alignment.py`（align 前按骨架签名分组：签名相同→同桶；不同→先尝试 LCS 相似度 ≥0.6 归并，否则新桶）
- Modify: `server/app/learning/skill.py`（induce 写 skill_strategy 行；skill.skeleton 存主桶，strategies 关联各桶）
- Modify: `server/app/api/cards.py`（card 返回 strategies 列表）
- Test: `server/tests/test_alignment.py` 追加

- [ ] Step 1: 红——两 session 路径 A/B（A: 输入+保存；B: 先选类型再输入+保存）→ align 出 1 个 alignment 含 2 桶；同签名 3 session → 1 桶。
- [ ] Step 2: 实现；单桶场景零行为变化（向后兼容）。
- [ ] Step 3: 绿 + 全量。

### Task 4: evidence_edge 基础表（TDD + 迁移）

**Files:**
- New: 迁移（evidence_edge：src/dst/type/evidence_count/first_seen/last_seen，spec §5）
- New: `server/app/learning/evidence.py`（从 alignment 骨架生成边：action→api（calls）、api→state（signals）、session→action（contains））
- Modify: `induce` 时同步写边（幂等：同 (src,dst,type) 累加 evidence_count 更新 last_seen）
- Test: `server/tests/test_evidence.py`

- [ ] Step 1: 红——induce 后边存在且计数正确；re-induce 幂等（不重复建边，计数累加）。
- [ ] Step 2: 实现 + 迁移。
- [ ] Step 3: 绿 + 全量。

### Task 5: 对比测量 + 真实流量采集实战

**Files:**
- Modify: `server/app/api/baseline.py`（/baseline/skills 加 source 维度与 demo 基线对比字段 `vs_baseline`）
- Modify: `server/web/src/views/SkillsList.vue`（卡片显示 source 徽标；新增"基线对比"区块）
- Test: baseline 端点 TDD 追加

**实战步骤（用户在旁）：**
- [ ] Step 1: 用户日常使用明搭云 30-60 分钟（常驻浏览器插件后台录，source=real_traffic）——不刻意、含走错/中断/废操作。
- [ ] Step 2: process 全部 real_traffic 会话（噪声过滤生效，查 filtered_windows 统计）。
- [ ] Step 3: align（跨多会话分桶）→ induce（真实 LLM）→ assertions → verify。
- [ ] Step 4: 对比报告：/baseline/skills 的 vs_baseline（真实流量 skill 置信度/断言通过率 vs demo 基线 80% 线）。
- [ ] Step 5: 工作台用户测试（截图入 demo/sprint10/）。

### Task 6: 验收 + 合并

- [ ] Step 1: 全量三套 + E2E（真实流量全链）。
- [ ] Step 2: demo/sprint10/README.md 验收记录 + 用户测试报告（含截图）。
- [ ] Step 3: lessons 补记 + 合并 main。
