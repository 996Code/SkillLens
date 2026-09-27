// 工作台 API 层（S9 Task 3/4/5）：fetch 封装（同源部署，base='' 零配置）。
// 类型定义与后端端点字段一一对齐：GET /skills、GET /skills/{id}/card（14 字段）、
// GET /reports/{id}、GET /expected-deltas/{id}、
// POST /expected-deltas/{id}/observe、GET /replay-runs/{id}。
// S21 块 S：authedFetch 统一带 Bearer token，401 → 清 token 跳 /login。

const BASE = "";

// ---------- S21 块 S：认证 ----------

const TOKEN_KEY = "sl_token";
const USER_KEY = "sl_user";

export interface AuthUser {
  id: number;
  username: string;
  role: "admin" | "reviewer" | "viewer";
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function currentUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

function setSession(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** 登录：成功存 token+user；失败抛 ApiError(401)。 */
export async function login(username: string, password: string): Promise<AuthUser> {
  const resp = await fetch(BASE + "/api/v1/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, "用户名或密码错误");
  }
  const body = (await resp.json()) as { token: string; user: AuthUser };
  setSession(body.token, body.user);
  return body.user;
}

/** 登出：后端失效 token + 本地清会话。 */
export async function logout(): Promise<void> {
  try {
    await fetch(BASE + "/api/v1/auth/logout", {
      method: "POST",
      headers: authHeaders(),
    });
  } catch {
    /* 后端不可达也照常清本地会话 */
  }
  clearSession();
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { authorization: `Bearer ${token}` } : {};
}

/** 统一出口：带 token；401 清会话跳登录（token 过期/被登出）。 */
async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const resp = await fetch(BASE + path, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers as Record<string, string> | undefined) },
  });
  if (resp.status === 401 && !path.startsWith("/api/v1/auth/login")) {
    clearSession();
    window.location.assign("/login");
  }
  return resp;
}

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function get<T>(path: string): Promise<T> {
  const resp = await authedFetch(path);
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
  superseded_by: number | null;
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
  external_ref: string | null; // S25 块 W3：Jira key 等外部条目编号
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

// ---------- 类型（S14 块H：编排画布） ----------

export interface CanvasSummary {
  id: number;
  name: string;
  created_at: string;
}

export interface CanvasNode {
  id: string;
  type: string; // change_source | impact_select | replay_batch | aggregate | review_output
  params: Record<string, unknown>;
  x: number;
  y: number;
}

export interface CanvasEdge {
  from: string;
  to: string;
}

export interface CanvasDag {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface CanvasDetail {
  id: number;
  name: string;
  dag: CanvasDag;
  created_at: string;
}

export interface CanvasRunSummary {
  id: number;
  status: string; // started | finished | error
  started_at: string | null;
  finished_at: string | null;
  node_count: number;
}

export interface CanvasNodeOutput {
  node: string;
  output: Record<string, unknown>;
}

export interface AgentRunDetail {
  id: number;
  status: string; // started | finished | error
  node_outputs: CanvasNodeOutput[] | null;
  input: Record<string, unknown> | null;
  error_text: string | null;
}

/** POST /canvas/{id}/run 实际返回体（后端 test_canvas.py 为规格）。 */
export interface CanvasRunResponse {
  id: number; // agent_run id
  canvas_id: number;
  status: string;
  graph_name: string;
  node_outputs: CanvasNodeOutput[] | null;
  error_text: string | null;
}

// ---------- 类型（S15 块 I：评审门户——夜间 agent_run 的 PR 式评审） ----------

export type ReviewDecision = "approved" | "rejected" | "changes_requested";

/** GET /reviews/pending 队列项：node_outputs 摘要透传，
 * review_output 段的 output.review 为 markdown 评审摘要（若有）。 */
export interface PendingRun {
  id: number;
  graph_name: string;
  status: string; // started | finished | error
  started_at: string;
  node_outputs: CanvasNodeOutput[];
}

export interface ReviewRunSummary {
  graph_name: string;
  status: string;
  started_at: string;
}

export interface ReviewItem {
  id: number;
  agent_run_id: number;
  reviewer: string;
  user_id: number | null;
  decision: ReviewDecision;
  comment: string | null;
  created_at: string;
  agent_run: ReviewRunSummary | null;
}

export interface CreateReviewRequest {
  agent_run_id: number;
  decision: ReviewDecision;
  comment?: string;
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

// ---------- S22 块 T：视觉回归基线 ----------

export interface VisualBaselineInfo {
  skill_id: number;
  file_path: string;
  image_hash: string;
  width: number;
  height: number;
  source_run_id: number;
  created_at: string;
}

export interface VisualCompareResult {
  run_id: number;
  run_status: string;
  passed: boolean;
  ts: string;
  payload: {
    kind: "visual_baseline";
    passed: boolean;
    hash_distance: number | null;
    diff_ratio: number | null;
    threshold: number;
    size_changed: boolean;
    error: string | null;
  };
}

export interface VisualBaselineResponse {
  baseline: VisualBaselineInfo | null;
  last_result: VisualCompareResult | null;
}

export function getVisualBaseline(
  id: number | string,
): Promise<VisualBaselineResponse> {
  return get<VisualBaselineResponse>(`/api/v1/skills/${id}/visual-baseline`);
}

/** 重置基线（reviewer/admin；下次 execute PASS 自动重建）。404 = 无基线。 */
export async function resetVisualBaseline(
  id: number | string,
): Promise<{ ok: boolean }> {
  const resp = await authedFetch(`/api/v1/skills/${id}/visual-baseline/reset`, {
    method: "POST",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `POST visual-baseline/reset -> ${resp.status}`);
  }
  return resp.json() as Promise<{ ok: boolean }>;
}

/** 拉取基线/最新截图为 blob URL（<img> 无法带 Authorization 头，经 fetch 转换）。 */
export async function fetchVisualImage(
  id: number | string,
  which: "baseline" | "latest",
): Promise<string> {
  const resp = await authedFetch(
    `/api/v1/skills/${id}/visual-baseline/image?which=${which}`);
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET visual image(${which}) -> ${resp.status}`);
  }
  return URL.createObjectURL(await resp.blob());
}

export function getReport(id: number | string): Promise<Report> {
  return get<Report>(`/api/v1/reports/${id}`);
}

// ---------- S25 块 W：Playwright 脚本导出 ----------

/** 导出 skill 为自包含 Playwright 脚本并触发浏览器下载。 */
export async function exportSkillPlaywright(id: number | string): Promise<void> {
  const resp = await authedFetch(`/api/v1/skills/${id}/export/playwright`);
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET export/playwright -> ${resp.status}`);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `skill_${id}_replay.py`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------- S24 块 U：定位修复提案（自愈闭环） ----------

export interface LocateProposalItem {
  id: number;
  skill_id: number;
  step_label: string;
  proposed_label: string;
  strategy: string;
  status: "proposed" | "verified" | "promoted" | "rejected";
  verify_count: number;
  source_run_id: number | null;
  applied_skill_id: number | null;
  attribution: string | null;
  created_at: string;
}

export function getLocateProposals(
  id: number | string,
): Promise<LocateProposalItem[]> {
  return get<LocateProposalItem[]>(`/api/v1/skills/${id}/locate-proposals`);
}

/** 人工否决提案（reviewer/admin）。rejected 不再参与回放自愈。 */
export async function rejectLocateProposal(
  id: number,
): Promise<{ ok: boolean }> {
  const resp = await authedFetch(`/api/v1/locate-proposals/${id}/reject`, {
    method: "POST",
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `POST locate-proposals/reject -> ${resp.status}`);
  }
  return resp.json() as Promise<{ ok: boolean }>;
}

// ---------- S23 块 V：性能上下文（报告页只读派生端点） ----------

export interface PerfContext {
  baseline: { median: number | null; n: number };
  current_ms: number | null;
  history_ms: number[];
}

export function getReportPerf(id: number | string): Promise<PerfContext> {
  return get<PerfContext>(`/api/v1/reports/${id}/perf`);
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
  const resp = await authedFetch(`/api/v1/expected-deltas/${deltaId}/observe`, {
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

/** S14 块H：画布 CRUD / 运行 / 运行详情。 */
export function listCanvases(): Promise<CanvasSummary[]> {
  return get<CanvasSummary[]>("/api/v1/canvas");
}

export function getCanvas(id: number | string): Promise<CanvasDetail> {
  return get<CanvasDetail>(`/api/v1/canvas/${id}`);
}

/** 保存画布（版本化新行）。422 = DAG 校验错误（detail 透出给界面）。 */
export async function saveCanvas(
  name: string,
  dag: CanvasDag,
): Promise<{ id: number }> {
  const resp = await authedFetch("/api/v1/canvas", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name, dag }),
  });
  if (!resp.ok) {
    let detail = `POST /canvas -> ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* 非 JSON 错误体，保留状态行 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<{ id: number }>;
}

export async function runCanvas(id: number | string): Promise<CanvasRunResponse> {
  const resp = await authedFetch(`/api/v1/canvas/${id}/run`, { method: "POST" });
  if (!resp.ok) {
    let detail = `POST /canvas/${id}/run -> ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* 非 JSON 错误体，保留状态行 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<CanvasRunResponse>;
}

export function listCanvasRuns(
  canvasId: number | string,
): Promise<CanvasRunSummary[]> {
  return get<CanvasRunSummary[]>(`/api/v1/canvas/${canvasId}/runs`);
}

/** agent_run 详情（节点着色/产物下钻）。404 = 非 canvas 图或不存在的 run。 */
export function getAgentRun(agentRunId: number | string): Promise<AgentRunDetail> {
  return get<AgentRunDetail>(`/api/v1/canvas/runs/${agentRunId}`);
}

// ---------- S15 块 I：评审门户端点 ----------

/** 未评审的 agent_run 队列（评审门户首页数据源）。 */
export function getPendingRuns(): Promise<PendingRun[]> {
  return get<PendingRun[]>("/api/v1/reviews/pending");
}

/** 已评审列表（id 倒序）。decision 过滤参数同样枚举校验（非法 422）。 */
export function getReviews(decision?: ReviewDecision): Promise<ReviewItem[]> {
  const qs = decision ? `?decision=${decision}` : "";
  return get<ReviewItem[]>(`/api/v1/reviews${qs}`);
}

/** 提交评审。422 = decision 非法；404 = agent_run 不存在；409 = 同 run 重复评审。 */
export async function createReview(
  body: CreateReviewRequest,
): Promise<ReviewItem> {
  const resp = await authedFetch("/api/v1/reviews", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = `POST /reviews -> ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* 非 JSON 错误体，保留状态行 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<ReviewItem>;
}

export { ApiError };

export interface GenericSkillItem {
  id: number;
  name: string;
  description: string;
  status: string;
  source_skill_ids: number[];
  slots_schema: { slot: string; description: string }[];
  notes: string;
}

export async function getGenericSkills(): Promise<GenericSkillItem[]> {
  return get("/api/v1/generic-skills") as Promise<GenericSkillItem[]>;
}
