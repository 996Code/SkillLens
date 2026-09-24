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

export function getReport(id: number | string): Promise<Report> {
  return get<Report>(`/api/v1/reports/${id}`);
}

export function getExpectedDelta(id: number | string): Promise<ExpectedDelta> {
  return get<ExpectedDelta>(`/api/v1/expected-deltas/${id}`);
}

export function getReplayRun(id: number | string): Promise<ReplayRunDetail> {
  return get<ReplayRunDetail>(`/api/v1/replay-runs/${id}`);
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
