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
    // 401=凭证错；5xx=服务端故障（别误导用户改密码）
    throw new ApiError(resp.status,
      resp.status === 401 ? "用户名或密码错误"
        : resp.status >= 500 ? "服务暂时不可用，请稍后重试"
          : `登录失败（${resp.status}）`);
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
export async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
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

/** 写请求统一出口（评审：4 处 POST detail 解析样板收口）：
 * 非 2xx 抛 ApiError——错误体带 detail 用 detail，否则回退状态行
 * （"METHOD /路径(去 /api/v1) -> 状态码"，与收口前逐字一致）。 */
async function send<T>(path: string, init: RequestInit): Promise<T> {
  const resp = await authedFetch(path, init);
  if (!resp.ok) {
    let detail =
      `${init.method ?? "POST"} ${path.replace("/api/v1", "")} -> ${resp.status}`;
    try {
      const j = (await resp.json()) as { detail?: string };
      if (j?.detail) detail = j.detail;
    } catch {
      /* 非 JSON 错误体，保留状态行 */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  };
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
  system: string; // S38：目标系统（后端 list 端点实际返回）
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
  flaky: boolean;
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
  duration_ms: number | null; // S34：run 详情页耗时
  flaky: boolean;
  created_at: string | null;
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

/** 触发执行观测（observe，同步返回：server 处理完才返回，无需轮询）。
 * 409 = 业务安全拒绝（delta 未确认 / shadow 未执行）。 */
export function replayObserve(
  deltaId: number | string,
  body: ObserveRequest,
): Promise<ObserveResponse> {
  return send<ObserveResponse>(
    `/api/v1/expected-deltas/${deltaId}/observe`, jsonInit("POST", body));
}

/** S14 块H：画布 CRUD / 运行 / 运行详情。 */
export function listCanvases(): Promise<CanvasSummary[]> {
  return get<CanvasSummary[]>("/api/v1/canvas");
}

export function getCanvas(id: number | string): Promise<CanvasDetail> {
  return get<CanvasDetail>(`/api/v1/canvas/${id}`);
}

/** 保存画布（版本化新行）。422 = DAG 校验错误（detail 透出给界面）。 */
export function saveCanvas(
  name: string,
  dag: CanvasDag,
): Promise<{ id: number }> {
  return send<{ id: number }>("/api/v1/canvas", jsonInit("POST", { name, dag }));
}

export function runCanvas(id: number | string): Promise<CanvasRunResponse> {
  return send<CanvasRunResponse>(`/api/v1/canvas/${id}/run`, { method: "POST" });
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

// AR1：POST /reviews 已冻结（410）。AR4 由场景报告评审恢复写入口。

// ---------- S32：链路时间线 + LLM IO 全留存 ----------

export interface TimelineItem {
  // S37-2 测试活动视角：主行 test_run | recording；
  // include_internal 时附带 llm | agent_run | report | review
  type: string;
  id: number | string;
  title: string;
  subtitle: string;
  ts: string;
  skills?: { id: number; name: string }[]; // recording 行的学习产出
}

export function getTimeline(
  limit = 100,
  includeInternal = false,
): Promise<TimelineItem[]> {
  return get<TimelineItem[]>(
    `/api/v1/timeline?limit=${limit}&include_internal=${includeInternal}`);
}

export interface LlmLogDetail {
  id: number;
  purpose: string;
  provider: string;
  model: string;
  prompt: string;
  response: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number;
  created_at: string;
}

/** 单条 LLM 调用完整 prompt/response（区别于列表 200 字符摘要）。 */
export function getLlmLogDetail(id: number | string): Promise<LlmLogDetail> {
  return get<LlmLogDetail>(`/api/v1/audit/llm-logs/${id}`);
}

/** S33：回放步骤截图（blob URL——<img> 无法带 Authorization 头，经 fetch 转换）。 */
export async function fetchStepScreenshot(
  runId: number | string,
  file: string,
): Promise<string> {
  const resp = await authedFetch(
    `/api/v1/replay-runs/${runId}/step-screenshot?file=${encodeURIComponent(file)}`);
  if (!resp.ok) {
    throw new ApiError(resp.status, `GET step-screenshot -> ${resp.status}`);
  }
  return URL.createObjectURL(await resp.blob());
}

// ---------- S38：统一流程图 ----------

export interface FlowNodeDTO {
  id: string;
  type: string; // page | action | state | assert
  label: string;
  status: string;
  screenshot?: string;
  io?: Record<string, unknown>;
}

export interface FlowGraphDTO {
  nodes: FlowNodeDTO[];
  edges: { from: string; to: string }[];
  run_id: number;
  run_status: string;
}

export function getRunFlow(runId: number | string): Promise<FlowGraphDTO> {
  return get<FlowGraphDTO>(`/api/v1/replay-runs/${runId}/flow`);
}

/** S39 自动化流程图（骨架+断言 → 节点图）。 */
export function getSkillFlow(skillId: number | string): Promise<FlowGraphDTO> {
  return get<FlowGraphDTO>(`/api/v1/skills/${skillId}/flow`);
}

// ---------- S43-2：图基座第二步（状态机归纳/学习图/画布子图） ----------

export interface StateMachineDTO {
  nodes: FlowNodeDTO[];
  edges: { from: string; to: string; count: number }[];
  initial: string[];
  final: string[];
}

export function getSkillStateMachine(
  skillId: number | string): Promise<StateMachineDTO> {
  return get<StateMachineDTO>(`/api/v1/skills/${skillId}/state-machine`);
}

export function getLearningGraph(): Promise<FlowGraphDTO> {
  return get<FlowGraphDTO>("/api/v1/learning-graph");
}

// ---------- S37-3：流程分组（自动化流程组合 → 一键执行 → 汇总） ----------

export interface SuiteSkillBrief {
  id: number;
  name: string;
  status: string;
  system: string;
}

export interface SuiteItem {
  id: number;
  name: string;
  skill_ids: number[];
  skills: SuiteSkillBrief[];
  scenario_id: number | null;
  migration_status: string;
  migration_reason: string;
  created_at: string;
}

export interface SuiteRunResult {
  skill_id: number;
  skill_name: string;
  run_id: number;
  status: string;
  mode: string;
}

export interface SuiteRunSummary {
  id: number;
  suite_id: number;
  total: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  shadow_count: number;
  results: SuiteRunResult[];
  created_at: string;
}

export function listSuites(): Promise<SuiteItem[]> {
  return get<SuiteItem[]>("/api/v1/suites");
}

export function listSuiteRuns(id: number): Promise<SuiteRunSummary[]> {
  return get<SuiteRunSummary[]>(`/api/v1/suites/${id}/runs`);
}

export { ApiError };

// ---------- S42-7：字段类型知识库（表单校验自愈资产，Web 可维护） ----------

export interface FieldTypeHintItem {
  id: number;
  label_pattern: string;
  field_type: string;
  example_value: string;
  source: string; // manual | learned
  source_skill_id: number | null;
  success_count: number;
  created_at: string;
}

export interface FieldTypeList {
  items: FieldTypeHintItem[];
  builtin_types: string[];
}

export function listFieldTypes(): Promise<FieldTypeList> {
  return get<FieldTypeList>("/api/v1/field-types");
}

export async function createFieldType(
  labelPattern: string, fieldType: string, exampleValue: string,
): Promise<FieldTypeHintItem> {
  const resp = await authedFetch("/api/v1/field-types", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label_pattern: labelPattern, field_type: fieldType,
                           example_value: exampleValue }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `POST field-types -> ${resp.status}`);
  }
  return resp.json() as Promise<FieldTypeHintItem>;
}

export async function updateFieldType(
  id: number, labelPattern: string, fieldType: string, exampleValue: string,
): Promise<FieldTypeHintItem> {
  const resp = await authedFetch(`/api/v1/field-types/${id}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label_pattern: labelPattern, field_type: fieldType,
                           example_value: exampleValue }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, `PUT field-types -> ${resp.status}`);
  }
  return resp.json() as Promise<FieldTypeHintItem>;
}

export async function deleteFieldType(id: number): Promise<{ ok: boolean }> {
  const resp = await authedFetch(`/api/v1/field-types/${id}`, { method: "DELETE" });
  if (!resp.ok) {
    throw new ApiError(resp.status, `DELETE field-types -> ${resp.status}`);
  }
  return resp.json() as Promise<{ ok: boolean }>;
}

// ---------- UI 优化批1：仪表盘数据（S28 端点此前无前端消费） ----------

export interface DashboardPayload {
  skills: { total: number; learned: number; candidate: number; generic_learned: number };
  replays: {
    total: number; pass: number; fail: number; error: number;
    shadow: number; flaky: number;
    recent: Array<{
      id: number; skill_id: number; skill_name: string;
      status: string; mode: string; flaky: boolean;
      duration_ms: number | null; ts: string;
    }>;
  };
  reports: { total: number; last: Record<string, number> | null };
  trend: Array<{ date: string; total: number; pass: number }>;
}

export function getDashboard(): Promise<DashboardPayload> {
  return get<DashboardPayload>("/api/v1/dashboard");
}

export interface SystemTrend {
  system: string; total: number; pass: number; fail: number;
  rate: number; e1_env: number; e2_infra: number; unverified_pass: number;
}

export function getSystemTrends(): Promise<SystemTrend[]> {
  return get<SystemTrend[]>("/api/v1/skills/trends");
}

export interface ReportListItem {
  id: number; expected_delta_id: number; observed_delta_id: number;
  created_at: string;
  expected_count: number; missing_count: number;
  unexpected_count: number; drift_count: number;
}

export function listReports(): Promise<ReportListItem[]> {
  return get<ReportListItem[]>("/api/v1/reports");
}

export interface FailureRunRow {
  id: number; skill_id: number; skill_name: string;
  status: string; failure_class: string | null;
  system: string; created_at: string;
}

export interface FailuresSummary {
  total: number; unclassified: number;
  by_class: Record<string, { count: number; label: string; runs: FailureRunRow[] }>;
}

export function getFailuresSummary(days = 30): Promise<FailuresSummary> {
  return get<FailuresSummary>(`/api/v1/failures/summary?days=${days}`);
}

export interface SkillRunRow {
  id: number; skill_id: number; status: string; mode: string;
  flaky: boolean; failure_class: string | null;
  duration_ms: number | null; created_at: string; steps: number;
}

export function listSkillRuns(skillId: number | string): Promise<SkillRunRow[]> {
  return get<SkillRunRow[]>(`/api/v1/skills/${skillId}/runs`);
}

export interface ConfirmedDeltaOption {
  id: number; requirement_id: string; feature: string;
  version: number; change_count: number; created_at: string;
}

export function listConfirmedDeltas(): Promise<ConfirmedDeltaOption[]> {
  return get<ConfirmedDeltaOption[]>("/api/v1/expected-deltas?status=confirmed");
}

// ---------- AR1：测试场景（Scenario）一等公民 ----------

export interface ScenarioStepBrief {
  skill_id: number | null;
  scenario_id: number | null;
  setup: boolean;
  enabled: boolean;
  overrides: Record<string, string>;
  cleanup: string | null;
  row_anchor_from: number | null;
  skill?: { id: number; name: string; description?: string;
            requires_confirmation?: boolean;
            fill_fields?: Array<{ name: string; first_value: string }> } | null;
}

export interface ScenarioDetail {
  id: number; name: string; system: string;
  status: string; definition_version: number; origin: string;
  steps: ScenarioStepBrief[]; created_at: string; updated_at: string;
}

export interface ScenarioListItem {
  id: number; name: string; system: string; status: string;
  definition_version: number; origin: string;
  steps: Array<{ skill_id: number | null }>; created_at: string;
  updated_at: string;
}

export function listScenarios(system?: string,
                              status?: string): Promise<ScenarioListItem[]> {
  const params = new URLSearchParams();
  if (system) params.set("system", system);
  if (status) params.set("status", status);
  const qs = params.toString();
  return get<ScenarioListItem[]>(`/api/v1/scenarios${qs ? `?${qs}` : ""}`);
}

export function getScenario(id: number | string): Promise<ScenarioDetail> {
  return get<ScenarioDetail>(`/api/v1/scenarios/${id}`);
}

// ---------- AR5：场景运行与场景报告 ----------

export interface ScenarioRunRow {
  id: number; scenario_id: number; trigger: string; executor: string;
  mode: string; status: string; source_track: string;
  confirm_side_effect: boolean | null;
  pass_count: number; fail_count: number; error_count: number;
  shadow_count: number; blocked_count: number; total_count: number;
  started_at: string | null; finished_at: string | null; created_at: string;
}

export interface ScenarioRunChild {
  id: number; skill_id: number; status: string; mode: string;
  execution_index: number | null; attempt: number;
  failure_class: string | null; duration_ms: number | null;
}

export interface ScenarioRunDetail extends ScenarioRunRow {
  definition_snapshot: { root: { scenario_id: number; definition_version: number };
                         steps: Array<{ execution_index: number; skill_id: number }> };
  runs: ScenarioRunChild[];
}

export function listScenarioRuns(scenarioId?: number,
                                 status?: string): Promise<ScenarioRunRow[]> {
  const params = new URLSearchParams();
  if (scenarioId) params.set("scenario_id", String(scenarioId));
  if (status) params.set("status", status);
  const qs = params.toString();
  return get<ScenarioRunRow[]>(`/api/v1/scenario-runs${qs ? `?${qs}` : ""}`);
}

export function getScenarioRun(id: number): Promise<ScenarioRunDetail> {
  return get<ScenarioRunDetail>(`/api/v1/scenario-runs/${id}`);
}

export interface ScenarioReportRow {
  id: number; scenario_run_id: number; scenario_id: number | null;
  status: string; coverage_state: string;
  expected_count: number; missing_count: number;
  unexpected_count: number; drift_count: number;
  review_state?: string; created_at: string;
}

export function listScenarioReports(): Promise<ScenarioReportRow[]> {
  return get<ScenarioReportRow[]>("/api/v1/scenario-reports");
}

export function getRunReport(runId: number): Promise<ScenarioReportRow & {
  deltas: Array<{ expectation_key: string; expected: unknown[];
                  missing: unknown[]; unexpected: unknown[]; drift: unknown[];
                  evidence_replay_run_ids: number[] }>;
}> {
  return get(`/api/v1/scenario-runs/${runId}/report`);
}

export interface PendingReview {
  report_id: number; scenario_run_id: number; scenario_id: number | null;
  coverage_state: string; missing_count: number; unexpected_count: number;
  drift_count: number; created_at: string;
}

export function getPendingReviews(): Promise<PendingReview[]> {
  return get<PendingReview[]>("/api/v1/reviews/pending");
}

export function reviewReport(reportId: number, decision: string,
                             comment?: string): Promise<{
  id: number; report_id: number; decision: string;
}> {
  return send(`/api/v1/reports/${reportId}/review`,
              jsonInit("POST", { decision, comment }));
}

export async function updateScenario(id: number | string,
                                     definitionVersion: number,
                                     body: {
  name: string; system: string;
  steps: Array<{ skill_id: number | null; scenario_id?: number | null;
    overrides?: Record<string, string>; enabled?: boolean;
    setup?: boolean; row_anchor_from?: number | null }>;
}): Promise<ScenarioDetail> {
  const resp = await authedFetch(`/api/v1/scenarios/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json",
               "If-Match": String(definitionVersion) },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(resp.status, `PATCH scenarios -> ${resp.status}`);
  return resp.json() as Promise<ScenarioDetail>;
}
