// 工作台 API 层（S9 Task 3/4/5）：fetch 封装（同源部署，base='' 零配置）。
// 类型定义与后端端点字段一一对齐：GET /skills、GET /skills/{id}/card（14 字段）、
// GET /reports/{id}、GET /expected-deltas/{id}、
// POST /expected-deltas/{id}/observe、GET /replay-runs/{id}。

const BASE = "";

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(BASE + path);
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET ${path} -> ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

// ---------- 类型（与 card 端点 14 字段对齐） ----------

export interface SkillListItem {
  id: number;
  alignment_id: number | null;
  name: string;
  description: string;
  status: string; // learned | candidate
  confidence: number;
  evidence_count: number;
  notes: string;
  source: string; // demo | real_traffic（S10：会话来源徽标）
}

export interface SkeletonStep {
  signature: string;
  session_window_seqs?: Record<string, number>;
}

export interface InputVariable {
  name: string;
  values: Record<string, string>; // session_id -> 采集值
}

export interface ParamVariable {
  param: string;
  values?: Record<string, string>;
  [k: string]: unknown;
}

export interface AssertionRow {
  id: number;
  kind: string; // api_status | state_signal | ui_text | field_change
  layer: number;
  payload: Record<string, unknown>;
}

export interface LastRun {
  id: number;
  status: string; // pass | fail | shadow | error
  mode: string; // shadow | execute
  ts: string;
}

export interface WindowParams {
  idle_ms?: number;
  max_window_ms?: number;
  consistent?: boolean;
  [k: string]: unknown;
}

export interface SkillCard {
  id: number;
  name: string;
  description: string;
  status: string;
  confidence: number;
  evidence_count: number;
  alignment_id: number | null;
  skeleton: SkeletonStep[];
  input_variables: InputVariable[];
  param_variables: ParamVariable[];
  assertions: AssertionRow[];
  last_run: LastRun | null;
  window_params: WindowParams | null;
  notes: string;
}

// ---------- 类型（报告页） ----------

export interface DeltaItem {
  type: string;
  value: string;
}

export interface Report {
  id: number;
  expected_delta_id: number;
  observed_delta_id: number;
  expected: DeltaItem[];
  missing: DeltaItem[];
  unexpected: DeltaItem[];
  drift: DeltaItem[];
  created_at: string;
}

export interface ExpectedDelta {
  id: number;
  requirement_id: string;
  feature: string;
  changes: DeltaItem[];
  status: string; // draft | confirmed
  reviewed_by: string;
  notes: string;
}

// ---------- 类型（S12 N1/N2：新功能增量发现） ----------

export interface DiscoveredFeatureItem {
  id: number;
  session_id: string;
  api_template: string | null; // null = 纯 UI 锚点 label 发现
  anchor_label: string | null;
  observed_count: number;
  status: string; // new | linked | dismissed
  linked_delta_id: number | null;
  first_seen: string;
  last_seen: string;
}

// ---------- 类型（回放触发与结果，Task 5） ----------

export interface ObserveRequest {
  skill_id: number;
  overrides: Record<string, string>;
  confirm_side_effect: boolean;
}

export interface ObserveResponse {
  id: number; // observed_delta id
  items: DeltaItem[];
  replay_run_id: number;
  replay_status: string; // pass | fail | shadow | error
}

export interface SnapshotForm {
  label: string;
  value: string;
}

export interface PageSnapshot {
  phase?: string;
  ts?: number;
  forms?: SnapshotForm[];
  labels?: { text: string }[];
  tables?: { label: string; rows: number }[];
  overflow?: boolean;
}

export interface ReplayPlan {
  url?: string;
  steps?: Record<string, unknown>[];
  before_snapshot?: PageSnapshot;
  after_snapshot?: PageSnapshot;
  [k: string]: unknown;
}

export interface AssertionResult {
  kind?: string; // replay-runs 的结果行带 kind（assert_eval 输出 payload+observed_status/passed/skipped）
  payload: Record<string, unknown>;
  observed_status: number | null;
  passed: boolean;
  skipped?: string;
}

export interface ReplayRunDetail {
  id: number;
  skill_id: number;
  mode: string; // shadow | execute
  status: string; // pass | fail | shadow | error
  plan: ReplayPlan | null;
  executed: Record<string, unknown>[] | null;
  assertion_results: AssertionResult[] | null;
  attribution: string | null;
  artifact_path: string;
}

// ---------- 类型（S12 N4 层5：断言观测一致性） ----------

export interface ConsistencyItem {
  assertion_id: number;
  kind: string;
  observed_values: unknown[]; // 各 replay_run 的 observed_status 集合（时序）
  consistent: boolean;
}

export interface SkillConsistency {
  skill_id: number;
  runs: number; // assertion_results 非空的 replay_run 数
  assertions: ConsistencyItem[]; // 无观测的断言（ui_text 等）不输出
  consistent: boolean;
  inconsistent_count: number;
}

// ---------- 类型（S10 基线对比，Task 5） ----------

export interface BaselineSide {
  count: number;
  avg_confidence: number | null;
  avg_pass_rate: number | null;
}

export interface BaselineCompare {
  demo: BaselineSide;
  real_traffic: BaselineSide;
  vs_baseline: {
    confidence_ratio: number | null;
    pass_rate_ratio: number | null;
    meets_c2: boolean;
  };
}

// ---------- 类型（S10.5 块M 审计页） ----------

export interface AuditSession {
  session_id: string;
  source: string; // demo | real_traffic
  note: string;
  created_at: string;
  event_count: number;
  filtered_count: number;
  semantic_action_count: number;
}

export interface EvidenceEdgeItem {
  src: string;
  dst: string;
  type: string; // contains | calls
  evidence_count: number;
  first_seen: string;
  last_seen: string;
}

export interface LlmLogItem {
  id: number;
  purpose: string;
  provider: string;
  model: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  created_at: string;
  prompt_head: string; // 界面摘要（200 字符），完整审计走 DB 直查
  response_head: string;
}

export interface TraceWindow {
  window_seq: number;
  anchor_type: string;
  anchor_label: string | null;
  kept: boolean;
  filter_reason: string;
  api_count: number;
  state_signal_count: number;
  has_state_snapshot: boolean;
}

export interface TraceSemanticAction {
  window_seq: number;
  anchor_label: string | null;
  api_templates: (string | null)[];
  state_before_forms: number | null;
  state_after_forms: number | null;
}

export interface TraceAlignment {
  id: number;
  skeleton_steps: number;
  bucket_count: number;
}

export interface TraceSkill {
  id: number;
  name: string;
  status: string;
  confidence: number;
}

export interface TraceReplayRun {
  id: number;
  status: string;
  mode: string;
  created_at: string;
}

export interface SessionTrace {
  session: AuditSession;
  windows: TraceWindow[];
  semantic_actions: TraceSemanticAction[];
  alignments: TraceAlignment[];
  skills: TraceSkill[];
  replay_runs: TraceReplayRun[];
}

// ---------- API 函数 ----------

export function getSkills(): Promise<SkillListItem[]> {
  return get<SkillListItem[]>("/api/v1/skills");
}

export function getBaselineCompare(): Promise<BaselineCompare> {
  return get<BaselineCompare>("/api/v1/baseline/compare");
}

export function getSkillCard(id: number | string): Promise<SkillCard> {
  return get<SkillCard>(`/api/v1/skills/${id}/card`);
}

/** S12 N4 层5：同 skill 多次 replay 的断言观测值一致性。 */
export function getSkillConsistency(id: number | string): Promise<SkillConsistency> {
  return get<SkillConsistency>(`/api/v1/skills/${id}/consistency`);
}

export function getReport(id: number | string): Promise<Report> {
  return get<Report>(`/api/v1/reports/${id}`);
}

export function getExpectedDelta(id: number | string): Promise<ExpectedDelta> {
  return get<ExpectedDelta>(`/api/v1/expected-deltas/${id}`);
}

export function getReplayRun(id: number | string): Promise<ReplayRunDetail> {
  return get<ReplayRunDetail>(`/api/v1/replay-runs/${id}`);
}

/** S12 N2：按 delta 查已链接的发现（报告页"已发现实现"徽标）。 */
export function getLinkedDiscoveries(
  deltaId: number | string,
): Promise<DiscoveredFeatureItem[]> {
  return get<DiscoveredFeatureItem[]>(
    `/api/v1/discoveries?status=linked&linked_delta_id=${deltaId}`);
}

// ---------- S10.5 块M：审计端点（全只读） ----------

export function getAuditSessions(): Promise<AuditSession[]> {
  return get<AuditSession[]>("/api/v1/audit/sessions");
}

export function getEvidenceEdges(
  type?: string,
  srcLike?: string,
): Promise<EvidenceEdgeItem[]> {
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  if (srcLike) params.set("src_like", srcLike);
  const qs = params.toString();
  return get<EvidenceEdgeItem[]>(`/api/v1/audit/evidence-edges${qs ? `?${qs}` : ""}`);
}

export function getLlmLogs(): Promise<LlmLogItem[]> {
  return get<LlmLogItem[]>("/api/v1/audit/llm-logs");
}

export function getSessionTrace(sessionId: string): Promise<SessionTrace> {
  return get<SessionTrace>(
    `/api/v1/audit/sessions/${encodeURIComponent(sessionId)}/trace`);
}

/** 触发回放观测（observe，同步返回：server 处理完才返回，无需轮询）。
 * 409 = 业务安全拒绝（delta 未确认 / shadow 未执行）。 */
export async function replayObserve(
  deltaId: number | string,
  body: ObserveRequest,
): Promise<ObserveResponse> {
  const resp = await fetch(BASE + `/api/v1/expected-deltas/${deltaId}/observe`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = `POST /expected-deltas/${deltaId}/observe -> ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* 非 JSON 错误体，保留状态行 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<ObserveResponse>;
}

export { ApiError };
