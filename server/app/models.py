from datetime import datetime, timezone

from sqlalchemy import BigInteger, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecordingSession(Base):
    __tablename__ = "recording_session"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    target_system: Mapped[str] = mapped_column(String(200), default="")
    note: Mapped[str] = mapped_column(String(500), default="")
    # Sprint 10 C2：会话来源标记（demo=演示基线 | real_traffic=真实用户流量）
    source: Mapped[str] = mapped_column(String(20), default="demo")


class RawEvent(Base):
    __tablename__ = "raw_event"
    __table_args__ = (
        UniqueConstraint("session_id", "page_id", "seq", name="uq_raw_event_session_page_seq"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SemanticAction(Base):
    __tablename__ = "semantic_action"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_seq: Mapped[int] = mapped_column()
    anchor_type: Mapped[str] = mapped_column(String(20))
    target: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    api_calls: Mapped[list] = mapped_column(JSON)
    state_signals: Mapped[list] = mapped_column(JSON)
    # Sprint 8 块B：锚点前后 UI 状态快照（kind="snapshot" 事件解析产物），旧数据为 NULL
    state_before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state_after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class NormalizedEvent(Base):
    __tablename__ = "normalized_event"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    event_id: Mapped[int] = mapped_column()
    template: Mapped[str] = mapped_column(String(500))
    page_id: Mapped[str] = mapped_column(String(40), default="")
    seq: Mapped[int] = mapped_column()
    ts: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TransactionWindow(Base):
    __tablename__ = "transaction_window"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    anchor_event_id: Mapped[int] = mapped_column()
    member_event_ids: Mapped[list] = mapped_column(JSON)
    idle_ms: Mapped[int] = mapped_column()
    max_window_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FilteredWindow(Base):
    """S10 Task2：噪声过滤决策审计（C3——不删 raw，可回放重过滤）。"""
    __tablename__ = "filtered_window"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    window_seq: Mapped[int] = mapped_column()
    reason: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Alignment(Base):
    __tablename__ = "alignment"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_ids: Mapped[list] = mapped_column(JSON)
    skeleton: Mapped[list] = mapped_column(JSON)
    param_variables: Mapped[list] = mapped_column(JSON)
    input_variables: Mapped[list] = mapped_column(JSON)
    window_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    buckets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FieldChange(Base):
    __tablename__ = "field_change"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    api_template: Mapped[str] = mapped_column(String(500))
    before_seq: Mapped[int] = mapped_column()
    after_seq: Mapped[int] = mapped_column()
    changes: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Skill(Base):
    __tablename__ = "skill"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alignment_id: Mapped[int] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    skeleton: Mapped[list] = mapped_column(JSON)
    param_variables: Mapped[list] = mapped_column(JSON)
    input_variables: Mapped[list] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column()
    evidence_count: Mapped[int] = mapped_column()
    notes: Mapped[str] = mapped_column(String(500), default="")
    # S15 版本演化（v3 §29 不覆盖旧版本）：re-induce 旧行 status→superseded 保留，
    # 新行 version=旧最大+1；superseded_by 链式指向直接后继（nullable，活跃行为 NULL）
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    superseded_by: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SkillStrategy(Base):
    """Skill 的可选路径（spec §5）：分桶对齐后每桶一条，主桶亦记录。"""
    __tablename__ = "skill_strategy"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    strategy_signature: Mapped[str] = mapped_column(Text)
    skeleton: Mapped[list] = mapped_column(JSON, nullable=True)
    evidence_count: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class EvidenceEdge(Base):
    """证据图边（spec §5）：全局证据资产，非 skill 私有（re-induce 不清）。"""
    __tablename__ = "evidence_edge"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    src: Mapped[str] = mapped_column(String(300))
    dst: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(30))
    evidence_count: Mapped[int] = mapped_column(default=1)
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)
    __table_args__ = (UniqueConstraint("src", "dst", "type",
                                        name="uq_evidence_edge"),)


class DiscoveredFeature(Base):
    """S12 N1：新功能增量发现（全局累加资产，同 evidence_edge 语义——不随 re-process 清）。

    - api_template 非空 = API 模板发现；为空 = 纯 UI 锚点 label 发现（anchor_label）；
    - session_id 记录最近一次贡献的会话（同会话重跑跳过累加，跨会话累加 observed_count）；
    - status: new（待确认）| linked（N2 confirm 对齐到 expected_delta）| dismissed。
    """
    __tablename__ = "discovered_feature"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    api_template: Mapped[str | None] = mapped_column(String(300), nullable=True)
    anchor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observed_count: Mapped[int] = mapped_column(default=1)
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="new")
    linked_delta_id: Mapped[int | None] = mapped_column(nullable=True)


class GenericSkill(Base):
    """S17 块 L：通用能力层资产（跨系统归纳的通用模板）。

    - status: candidate（归纳落库默认，含回查失败）| learned（promote 晋升后）；
    - slots_schema: [{slot, description, examples: {skill_id: 值}}]——LLM 提议、
      确定性回查（每个 examples 值必须能在源 skill 骨架/变量/断言中找到）；
    - source_skill_ids/evidence_refs：源 skill 引用与证据引用（骨架步数/变量名）。
    """
    __tablename__ = "generic_skill"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    slots_schema: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    source_skill_ids: Mapped[list] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DevPlan(Base):
    """S18 T1：夜间开发计划（需求 → LLM 结构化字段变更清单）。

    - status: draft（生成落库默认，含回查失败）| confirmed（人工 confirm 后，
      C1 延伸门控）| executed | error（T3 执行器状态）；
    - changes: [{op: "add_field", field_type, label, key}]——LLM 提议、
      确定性回查（op/field_type 白名单 + key 格式 + target_form 已知）；
    - execution_log: T3 执行器逐步动作+响应摘要（C3），生成阶段为 NULL；
    - notes: 回查失败原因（plan 仍落库 draft，人工看 notes 修订——
      与 expected_delta 同模式）。
    """
    __tablename__ = "dev_plan"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement_text: Mapped[str] = mapped_column(Text)
    target_form: Mapped[str] = mapped_column(String(100))
    changes: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    execution_log: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purpose: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class OutcomeAssertion(Base):
    __tablename__ = "outcome_assertion"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    layer: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(30))
    api_template: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict] = mapped_column(JSON)
    # S12 N4 层4：verify 通过次数（历史成功样本背书，>=3 → payload.layer4_verified）
    evidence_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ReplayRun(Base):
    __tablename__ = "replay_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    plan: Mapped[dict] = mapped_column(JSON)
    executed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    assertion_results: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_path: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExpectedDelta(Base):
    __tablename__ = "expected_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement_id: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[str] = mapped_column()
    requirement_text: Mapped[str] = mapped_column(Text)
    feature: Mapped[str] = mapped_column(String(100), default="")
    changes: Mapped[list] = mapped_column(JSON)          # [{"type","value"}]
    status: Mapped[str] = mapped_column(String(20))      # draft|confirmed
    reviewed_by: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ObservedDelta(Base):
    __tablename__ = "observed_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expected_delta_id: Mapped[int] = mapped_column(index=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    replay_run_id: Mapped[int] = mapped_column()
    items: Mapped[list] = mapped_column(JSON)            # 同 changes 结构
    duration_ms: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AgentRun(Base):
    """S13 F1：Agent 图执行记录（C3——节点产物逐段落库，含失败运行）。"""
    __tablename__ = "agent_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    graph_name: Mapped[str] = mapped_column(String(50))
    input: Mapped[dict] = mapped_column(JSON)
    node_outputs: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))  # started|finished|error
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_text: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CanvasDag(Base):
    """S14 H2：编排画布 DAG（版本化保存——每次保存新行，不覆盖旧版本）。"""
    __tablename__ = "canvas_dag"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    dag: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class DeltaReport(Base):
    __tablename__ = "delta_report"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expected_delta_id: Mapped[int] = mapped_column(index=True)
    observed_delta_id: Mapped[int] = mapped_column(index=True)
    expected: Mapped[list] = mapped_column(JSON)
    missing: Mapped[list] = mapped_column(JSON)
    unexpected: Mapped[list] = mapped_column(JSON)
    drift: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Review(Base):
    """S15 I1：夜间 agent_run 的人工评审行（C3——决策落库可审计）。

    同一 agent_run 仅允许一条评审（DB 唯一约束 + API 层 409 双保险）；decision 三选一
    approved|rejected|changes_requested（API 层 Literal 校验 422）。
    """
    __tablename__ = "review"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_run_id: Mapped[int] = mapped_column(index=True, unique=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
