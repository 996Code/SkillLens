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
    api_template: Mapped[str | None] = mapped_column(String(300), nullable=True,
                                                     index=True)
    anchor_label: Mapped[str | None] = mapped_column(String(200), nullable=True,
                                                     index=True)
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


class SynthFlow(Base):
    """S19 T1：流程生成（证据支撑的目标分解 → 从未演示过的新流程）。

    - status: proposed（生成落库默认，含回查失败）| executed | failed（T2）；
    - steps: [{kind: goto|input|click, target, value?}]——LLM 只做目标分解，
      确定性回查（verify_steps：每步 target 必须在证据集合中）；
    - evidence_refs: 生成时引用的证据快照（skill_ids/anchors/variables/
      pages/api_templates），供人工核对与 T4 真机演示追溯；
    - notes: 回查失败原因（仍落库供人工看）或执行成功后的自学习提示；
    - execution_log: T2 执行器每步结果（{step, kind, target, ok, error?}），
      生成阶段为 NULL。
    """
    __tablename__ = "synth_flow"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    goal: Mapped[str] = mapped_column(Text)
    system_hint: Mapped[str] = mapped_column(String(200))
    steps: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    notes: Mapped[str] = mapped_column(String(500), default="")
    evidence_refs: Mapped[list] = mapped_column(JSON)
    execution_log: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class TestSuite(Base):
    """S37-3 测试套件：操作流程组合（用户以套件为单位组织测试）。

    - skill_ids: 组合的操作流程清单（JSON）
    - suite_run 执行历史见 SuiteRun
    """
    __tablename__ = "test_suite"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    skill_ids: Mapped[list] = mapped_column(JSON)
    # S38 套件↔流水线合并：指向最新版本 canvas_dag（套件=线性流水线）
    canvas_id: Mapped[int | None] = mapped_column(nullable=True)
    # AR1：legacy Suite 定义向 Scenario 的确定性迁移记账。混合/未知系统
    # 不猜测转换，保留原因供开发者审计。
    scenario_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    migration_status: Mapped[str] = mapped_column(String(30), default="pending")
    migration_reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SuiteRun(Base):
    """S37-3 套件执行记录：一次套件运行 = 逐操作流程自动测试 + 汇总。

    - results: [{skill_id, skill_name, run_id, status, mode}]
    - pass_count/fail_count/error_count/shadow_count/total 汇总
    """
    __tablename__ = "suite_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    suite_id: Mapped[int] = mapped_column(index=True)
    # S38：执行走画布运行机制，agent_run 存全量节点产物（可下钻）
    agent_run_id: Mapped[int | None] = mapped_column(nullable=True)
    results: Mapped[list] = mapped_column(JSON)
    total: Mapped[int] = mapped_column(default=0)
    pass_count: Mapped[int] = mapped_column(default=0)
    fail_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    shadow_count: Mapped[int] = mapped_column(default=0)
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
    # S23 块 V：execute 回放耗时（ms）——性能基线与漂移判定的原始数据
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    # S24 块 U：flaky 标记——首试 fail 重试 pass（两次结果不一致），进一致性统计
    # AJ1 失败分类（e1_env/e2_infra/e3_drift/e4_expected；null=pass/未分类）
    failure_class: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    flaky: Mapped[bool] = mapped_column(default=False)
    # AG1：执行后端标记（server|extension）——插件执行端 run 可区分
    executor: Mapped[str] = mapped_column(String(20), default="server")
    # AR2：场景运行归属（闭包展开后的有序步号；历史无法确定者为空）
    scenario_run_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    execution_index: Mapped[int | None] = mapped_column(nullable=True)
    attempt: Mapped[int] = mapped_column(default=1)
    scope_kind: Mapped[str] = mapped_column(String(20), default="scenario")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # 健壮性体检🟡：收割判据落列（原在 plan.executor_state.last_step_at
    # ——收割须整行反序列化 MB 级 JSON；列化后索引直查）
    last_step_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ScenarioExpectation(Base):
    """AR4 场景期望绑定：人工确认的 expected_delta 与场景的活性关系。

    SQLite NULL 不参与 UNIQUE——场景级/步骤级分别用部分唯一索引（迁移建）。
    """
    __tablename__ = "scenario_expectation"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(index=True)
    expected_delta_id: Mapped[int] = mapped_column(index=True)
    # null=场景级（聚合全部业务步）；有值=步骤级（该场景局部索引）
    step_index: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ScenarioReport(Base):
    """AR4 场景运行自动报告：一 run 一报告（unique）。

    无期望不是失败——coverage_state=no_expectation 显式标记未覆盖。
    """
    __tablename__ = "scenario_report"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_run_id: Mapped[int] = mapped_column(unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="generating")
    coverage_state: Mapped[str] = mapped_column(String(20),
                                                default="no_expectation")
    source_track: Mapped[str] = mapped_column(String(20), default="demo")
    expected_count: Mapped[int] = mapped_column(default=0)
    missing_count: Mapped[int] = mapped_column(default=0)
    unexpected_count: Mapped[int] = mapped_column(default=0)
    drift_count: Mapped[int] = mapped_column(default=0)
    attempt_count: Mapped[int] = mapped_column(default=1)
    last_attempt_at: Mapped[datetime | None] = mapped_column(nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


class ReportDelta(Base):
    """AR4 单期望绑定的四分类明细（expectation_key 防重）。"""
    __tablename__ = "report_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_report_id: Mapped[int] = mapped_column(index=True)
    expectation_key: Mapped[str] = mapped_column(String(64))
    expected_delta_id: Mapped[int] = mapped_column()
    observed_delta_ids: Mapped[list] = mapped_column(JSON, default=list)
    evidence_replay_run_ids: Mapped[list] = mapped_column(JSON, default=list)
    expected: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    unexpected: Mapped[list] = mapped_column(JSON, default=list)
    drift: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    __table_args__ = (
        UniqueConstraint("scenario_report_id", "expectation_key",
                         name="uq_report_delta_key"),
    )


class ReportReview(Base):
    """AR4 报告评审：一报告一评审（unique），决策不可变。"""
    __tablename__ = "report_review"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(unique=True, index=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ScenarioRun(Base):
    """AR2 场景级聚合运行：一次场景执行 = 递归闭包快照 + 有序子 ReplayRun。

    状态机 queued→running→pass|fail|error|shadow|aborted（终态不可变）。
    C1 定格在 confirm_side_effect；C2 source_track 服务端推导（客户端不可写）。
    """
    __tablename__ = "scenario_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenario_id: Mapped[int] = mapped_column(index=True)
    definition_version: Mapped[int] = mapped_column()
    definition_snapshot: Mapped[dict] = mapped_column(JSON)
    # AR4 前置：期望绑定随运行定格（无绑定时空列表）
    expectation_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    trigger: Mapped[str] = mapped_column(String(20), default="api")
    executor: Mapped[str] = mapped_column(String(20), default="server")
    mode: Mapped[str] = mapped_column(String(10), default="execute")
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    source_track: Mapped[str] = mapped_column(String(20), default="demo")
    confirm_side_effect: Mapped[bool | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    requested_by_user_id: Mapped[int | None] = mapped_column(nullable=True)
    pass_count: Mapped[int] = mapped_column(default=0)
    fail_count: Mapped[int] = mapped_column(default=0)
    error_count: Mapped[int] = mapped_column(default=0)
    shadow_count: Mapped[int] = mapped_column(default=0)
    blocked_count: Mapped[int] = mapped_column(default=0)
    total_count: Mapped[int] = mapped_column(default=0)
    failure_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class ExpectedDelta(Base):
    __tablename__ = "expected_delta"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    requirement_id: Mapped[str] = mapped_column(String(100), index=True)
    # S25 块 W3：外部需求条目编号（Jira key 等；v1 仅存字段+展示，不做 API 对接）
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
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
    # S21 块 S：评审人关联账号（存量行 NULL，展示仍以 reviewer 字符串为准）
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class User(Base):
    """S21 块 S：工作台账号。角色三级 admin（建号/全权）> reviewer（可评审）> viewer（只读）。"""
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="viewer")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuthToken(Base):
    """S21 块 S：DB 会话——只存 token 哈希（secrets.token_urlsafe 签发，SHA-256 落库）。"""
    __tablename__ = "auth_token"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class LocateProposal(Base):
    """S24 块 U：定位修复提案库——LLM 提案 + 确定性验证（locate 实测）。

    状态机：proposed（LLM 提案未验证，不参与回放）→ verified（locate 实测命中，
    参与回放自愈）→ promoted（verify_count ≥ N 自动晋升）；任何状态可人工 rejected。
    source_run_id 关联首次定位失败的回放（U3 归因链）。
    """
    __tablename__ = "locate_proposal"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(index=True)
    step_label: Mapped[str] = mapped_column(String(200))
    proposed_label: Mapped[str] = mapped_column(String(200))
    strategy: Mapped[str] = mapped_column(String(30), default="")
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    verify_count: Mapped[int] = mapped_column(default=0)
    source_run_id: Mapped[int | None] = mapped_column(nullable=True)
    # S26：晋升回写生成的新版本 skill id（自愈闭环收口）
    applied_skill_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class VisualBaseline(Base):
    """S22 块 T：skill 视觉基线——首次 execute PASS 截图存档，此后回放比对。

    每 skill 至多一行（唯一约束）；重置=删行删文件，下次 PASS 重建。
    """
    __tablename__ = "visual_baseline"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    skill_id: Mapped[int] = mapped_column(unique=True, index=True)
    file_path: Mapped[str] = mapped_column(String(300))
    image_hash: Mapped[str] = mapped_column(String(16), default="")
    width: Mapped[int] = mapped_column(default=0)
    height: Mapped[int] = mapped_column(default=0)
    source_run_id: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class FieldTypeHint(Base):
    """S42-7 字段类型知识库（表单自愈资产）：字段语义 → 类型 → 合法值生成。

    回放遇 JS 校验拦截（点击提交但表单校验不过）时：按 label 匹配类型 →
    生成合法值 → 换值重试；成功后自动沉淀/计数（自我反哺）。内置规则为
    种子（source=builtin），Web 页面可增删改（source=manual），
    自愈成功自动写入（source=learned）——三者同库同权，按 success_count 排序。
    """
    __tablename__ = "field_type_hint"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    label_pattern: Mapped[str] = mapped_column(String(100), index=True)
    field_type: Mapped[str] = mapped_column(String(30))
    example_value: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(20), default="learned")
    source_skill_id: Mapped[int | None] = mapped_column(nullable=True)
    success_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Scenario(Base):
    """AR1 测试场景：用户工作层的一等业务流程。

    steps 保持 JSON，子场景引用使用 scenario_id。definition_version 保护
    并发编辑；有历史的场景只归档，不物理删除。
    """
    __tablename__ = "scenario"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    system: Mapped[str] = mapped_column(String(40), index=True)
    steps: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    definition_version: Mapped[int] = mapped_column(default=1)
    origin: Mapped[str] = mapped_column(String(30), default="manual")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
