<script setup lang="ts">
// S10.5 块M：链路审计页（C3 可视化）。单页四区块从上到下（无 tab）：
//   ① 会话列表（行点击展开链路下钻） ② 链路下钻（窗口→语义动作→对齐→Skill→回放）
//   ③ 证据图（type/src 过滤）        ④ LLM 调用日志（行点击展开 prompt/response 摘要）
// 全只读；LLM 日志只展示 200 字符界面摘要（完整审计走 DB 直查，不外泄全量）。
import { onMounted, ref } from "vue";
import {
  getAuditSessions,
  getEvidenceEdges,
  getLlmLogs,
  getSessionTrace,
} from "../api";
import type {
  AuditSession,
  EvidenceEdgeItem,
  LlmLogItem,
  SessionTrace,
} from "../api";

// ---------- ① 会话列表 ----------
const sessions = ref<AuditSession[]>([]);
const sessionsLoading = ref(true);
const sessionsError = ref("");

// ---------- ② 链路下钻 ----------
const selectedSid = ref("");
const trace = ref<SessionTrace | null>(null);
const traceLoading = ref(false);
const traceError = ref("");

let traceSeq = 0; // 竞态守卫：快速切换会话时晚到响应不得覆盖新选中

async function selectSession(s: AuditSession): Promise<void> {
  if (selectedSid.value === s.session_id) return; // 重复点击不重复拉取
  selectedSid.value = s.session_id;
  trace.value = null;
  traceError.value = "";
  traceLoading.value = true;
  const seq = ++traceSeq;
  try {
    const t = await getSessionTrace(s.session_id);
    if (seq !== traceSeq) return; // 已切到别的会话，丢弃
    trace.value = t;
  } catch (e) {
    if (seq !== traceSeq) return;
    traceError.value = e instanceof Error ? e.message : String(e);
  } finally {
    if (seq === traceSeq) traceLoading.value = false;
  }
}

// ---------- ③ 证据图 ----------
const edgeType = ref(""); // '' = 全部
const edgeSrcLike = ref("");
const edges = ref<EvidenceEdgeItem[]>([]);
const edgesLoading = ref(false);
const edgesError = ref("");

async function loadEdges(): Promise<void> {
  edgesLoading.value = true;
  edgesError.value = "";
  try {
    edges.value = await getEvidenceEdges(edgeType.value || undefined, edgeSrcLike.value.trim() || undefined);
  } catch (e) {
    edgesError.value = e instanceof Error ? e.message : String(e);
  } finally {
    edgesLoading.value = false;
  }
}

// ---------- ④ LLM 日志 ----------
const logs = ref<LlmLogItem[]>([]);
const logsLoading = ref(true);
const logsError = ref("");
const expandedLogId = ref<number | null>(null);

function toggleLog(id: number): void {
  expandedLogId.value = expandedLogId.value === id ? null : id;
}

// ---------- 展示辅助 ----------
function sidShort(sid: string): string {
  return sid.slice(0, 8);
}

function sourceLabel(s: string): string {
  return s === "real_traffic" ? "真实流量" : "演示";
}

function sourceCls(s: string): string {
  return s === "real_traffic" ? "badge-real" : "badge-demo";
}

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "");
}

function confPct(c: number): string {
  return `${Math.round(c * 100)}%`;
}

function formsLabel(n: number | null): string {
  return n === null ? "—" : String(n);
}

onMounted(async () => {
  // 三区块独立拉取：任一失败只降级自身区块，不阻塞其余
  try {
    sessions.value = await getAuditSessions();
  } catch (e) {
    sessionsError.value = e instanceof Error ? e.message : String(e);
  } finally {
    sessionsLoading.value = false;
  }
  await loadEdges();
  try {
    logs.value = await getLlmLogs();
  } catch (e) {
    logsError.value = e instanceof Error ? e.message : String(e);
  } finally {
    logsLoading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>审计</h1>
    <p class="muted page-desc">
      C3 全链路落库的可视化入口：会话 → 窗口过滤 → 语义动作 → 对齐 → Skill → 回放，
      以及证据边与 LLM 调用摘要（均为只读视图）。
    </p>

    <!-- ① 会话列表 -->
    <div class="block">
      <h2>会话列表</h2>
      <p v-if="sessionsLoading" class="muted">加载中…</p>
      <p v-else-if="sessionsError" class="error">加载失败：{{ sessionsError }}</p>
      <p v-else-if="sessions.length === 0" class="muted empty-line">暂无会话，先录制一轮操作</p>
      <table v-else class="tbl" data-testid="session-table">
        <thead>
          <tr>
            <th>会话</th><th>来源</th><th>备注</th><th>时间</th>
            <th>事件数</th><th>过滤数</th><th>语义动作数</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="s in sessions"
            :key="s.session_id"
            :class="{ 'row-selected': s.session_id === selectedSid }"
            class="row-click"
            @click="selectSession(s)"
          >
            <td class="mono" :title="s.session_id">{{ sidShort(s.session_id) }}</td>
            <td>
              <span class="badge" :class="sourceCls(s.source)" data-testid="source-badge">
                {{ sourceLabel(s.source) }}
              </span>
            </td>
            <td>{{ s.note || "—" }}</td>
            <td>{{ fmtTime(s.created_at) }}</td>
            <td>{{ s.event_count }}</td>
            <td>{{ s.filtered_count }}</td>
            <td>{{ s.semantic_action_count }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="sessions.length" class="muted hint">点击行查看该会话的链路下钻。</p>
    </div>

    <!-- ② 链路下钻（选中会话时显示） -->
    <div v-if="selectedSid" class="block" data-testid="trace-block">
      <h2>链路下钻：{{ sidShort(selectedSid) }}</h2>
      <p v-if="traceLoading" class="muted">链路加载中…</p>
      <p v-else-if="traceError" class="error">链路加载失败：{{ traceError }}</p>

      <template v-else-if="trace">
        <!-- 窗口层（M4：kept/reason 决策可视化） -->
        <h3>窗口（{{ trace.windows.length }}）</h3>
        <p v-if="trace.windows.length === 0" class="muted">无窗口</p>
        <table v-else class="tbl">
          <thead>
            <tr>
              <th>seq</th><th>锚点</th><th>决策</th>
              <th>API 数</th><th>状态信号数</th><th>状态快照</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="w in trace.windows" :key="w.window_seq">
              <td>{{ w.window_seq }}</td>
              <td>
                <span class="chip chip-kind">{{ w.anchor_type || "—" }}</span>
                <span v-if="w.anchor_label">{{ w.anchor_label }}</span>
              </td>
              <td>
                <span v-if="w.kept" class="badge badge-kept">保留</span>
                <span v-else class="badge badge-filtered">
                  已过滤<span v-if="w.filter_reason">（{{ w.filter_reason }}）</span>
                </span>
              </td>
              <td>{{ w.api_count }}</td>
              <td>{{ w.state_signal_count }}</td>
              <td>{{ w.has_state_snapshot ? "有" : "无" }}</td>
            </tr>
          </tbody>
        </table>

        <!-- 语义动作层 -->
        <h3>语义动作（{{ trace.semantic_actions.length }}）</h3>
        <p v-if="trace.semantic_actions.length === 0" class="muted">无</p>
        <ul v-else class="sa-list">
          <li v-for="a in trace.semantic_actions" :key="a.window_seq" class="sa-item">
            <span class="sa-anchor">W{{ a.window_seq }} {{ a.anchor_label || "（无锚点标签）" }}</span>
            <span class="sa-apis">
              <span v-for="(t, i) in a.api_templates" :key="i" class="chip mono">{{ t || "—" }}</span>
              <span v-if="a.api_templates.length === 0" class="muted">无 API</span>
            </span>
            <span class="sa-forms muted">
              前快照 forms {{ formsLabel(a.state_before_forms) }} /
              后快照 forms {{ formsLabel(a.state_after_forms) }}
            </span>
          </li>
        </ul>

        <!-- 对齐层 -->
        <h3>对齐（{{ trace.alignments.length }}）</h3>
        <p v-if="trace.alignments.length === 0" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>id</th><th>骨架步数</th><th>分桶数</th></tr></thead>
          <tbody>
            <tr v-for="a in trace.alignments" :key="a.id">
              <td>#{{ a.id }}</td>
              <td>{{ a.skeleton_steps }}</td>
              <td>{{ a.bucket_count }}</td>
            </tr>
          </tbody>
        </table>

        <!-- Skill 层 -->
        <h3>Skills（{{ trace.skills.length }}）</h3>
        <p v-if="trace.skills.length === 0" class="muted">无</p>
        <ul v-else class="skill-list">
          <li v-for="s in trace.skills" :key="s.id">
            <RouterLink :to="`/skills/${s.id}`">{{ s.name }}</RouterLink>
            <span class="badge" :class="s.status === 'learned' ? 'badge-learned' : 'badge-candidate'">{{ s.status }}</span>
            <span class="muted">置信度 {{ confPct(s.confidence) }}</span>
          </li>
        </ul>

        <!-- 回放历史 -->
        <h3>回放历史（{{ trace.replay_runs.length }}）</h3>
        <p v-if="trace.replay_runs.length === 0" class="muted">未回放</p>
        <table v-else class="tbl">
          <thead><tr><th>id</th><th>状态</th><th>模式</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="r in trace.replay_runs" :key="r.id">
              <td>#{{ r.id }}</td>
              <td><span class="dot" :class="`dot-${r.status}`"></span>{{ r.status }}</td>
              <td>{{ r.mode }}</td>
              <td>{{ fmtTime(r.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </template>
    </div>

    <!-- ③ 证据图 -->
    <div class="block">
      <h2>证据图</h2>
      <div class="edge-filter">
        <label>
          类型
          <select v-model="edgeType" @change="loadEdges" aria-label="边类型">
            <option value="">全部</option>
            <option value="contains">contains</option>
            <option value="calls">calls</option>
          </select>
        </label>
        <label>
          src 模糊
          <input
            v-model="edgeSrcLike"
            type="text"
            placeholder="src 包含…"
            @keyup.enter="loadEdges"
          />
        </label>
        <button type="button" @click="loadEdges">过滤</button>
      </div>
      <p v-if="edgesLoading" class="muted">加载中…</p>
      <p v-else-if="edgesError" class="error">加载失败：{{ edgesError }}</p>
      <p v-else-if="edges.length === 0" class="muted empty-line">暂无证据边</p>
      <table v-else class="tbl" data-testid="edge-table">
        <thead>
          <tr>
            <th>src → dst</th><th>类型</th><th>证据数</th><th>首见</th><th>最近</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in edges" :key="`${e.src}|${e.dst}|${e.type}`">
            <td class="mono">{{ e.src }} → {{ e.dst }}</td>
            <td><span class="chip chip-kind">{{ e.type }}</span></td>
            <td>{{ e.evidence_count }}</td>
            <td>{{ fmtTime(e.first_seen) }}</td>
            <td>{{ fmtTime(e.last_seen) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- ④ LLM 日志 -->
    <div class="block">
      <h2>LLM 调用日志</h2>
      <p class="muted hint">
        界面只展示 200 字符摘要（C3 全链路落库，完整 prompt/response 审计走 DB 直查）。
      </p>
      <p v-if="logsLoading" class="muted">加载中…</p>
      <p v-else-if="logsError" class="error">加载失败：{{ logsError }}</p>
      <p v-else-if="logs.length === 0" class="muted empty-line">暂无 LLM 调用</p>
      <table v-else class="tbl" data-testid="llm-table">
        <thead>
          <tr>
            <th>purpose</th><th>provider</th><th>model</th>
            <th>tokens（p/c）</th><th>耗时</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="l in logs" :key="l.id">
            <tr class="row-click" @click="toggleLog(l.id)">
              <td><span class="chip chip-kind">{{ l.purpose }}</span></td>
              <td>{{ l.provider }}</td>
              <td class="mono">{{ l.model }}</td>
              <td>{{ l.prompt_tokens ?? "—" }} / {{ l.completion_tokens ?? "—" }}</td>
              <td>{{ l.latency_ms == null ? "—" : `${l.latency_ms}ms` }}</td>
              <td>{{ fmtTime(l.created_at) }}</td>
            </tr>
            <tr v-if="expandedLogId === l.id" class="log-detail-row">
              <td colspan="6">
                <div class="log-detail" data-testid="log-detail">
                  <p class="log-head">prompt_head</p>
                  <pre class="code">{{ l.prompt_head || "（空）" }}</pre>
                  <p class="log-head">response_head</p>
                  <pre class="code">{{ l.response_head || "（空）" }}</pre>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-if="logs.length" class="muted hint">点击行展开 prompt/response 摘要。</p>
    </div>
  </section>
</template>

<style scoped>
.page-desc {
  margin-top: 0;
  font-size: 13px;
}
.block {
  margin-top: 28px;
}
.block h2 {
  font-size: 16px;
  border-bottom: 1px solid #eee;
  padding-bottom: 6px;
}
.block h3 {
  font-size: 14px;
  margin: 18px 0 6px;
}
.hint {
  font-size: 12px;
  margin: 6px 0 0;
}
.empty-line {
  margin: 8px 0;
}
.tbl {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
.tbl th,
.tbl td {
  border: 1px solid #e3e6ea;
  text-align: left;
  padding: 6px 10px;
  vertical-align: top;
}
.tbl th {
  background: #f6f8fa;
}
.row-click {
  cursor: pointer;
}
.row-click:hover {
  background: #f6f8fa;
}
.row-selected,
.row-selected:hover {
  background: #e8f0fe;
}
.badge {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
  white-space: nowrap;
}
.badge-demo {
  color: #555;
  background: #eee;
}
.badge-real {
  color: #1e7e34;
  background: #e6f4ea;
}
.badge-learned {
  color: #1e7e34;
  background: #e6f4ea;
}
.badge-candidate {
  color: #555;
  background: #eee;
}
.badge-kept {
  color: #1e7e34;
  background: #e6f4ea;
}
.badge-filtered {
  color: #c62828;
  background: #fdecea;
}
.chip {
  display: inline-block;
  background: #eef2f7;
  border-radius: 4px;
  padding: 0 6px;
  margin: 0 6px 2px 0;
  font-size: 12px;
}
.chip-kind {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  word-break: break-all;
}
.sa-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sa-item {
  border: 1px solid #e3e6ea;
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sa-anchor {
  font-weight: 600;
  font-size: 13px;
}
.sa-apis {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.sa-forms {
  font-size: 12px;
}
.skill-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.skill-list li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.edge-filter {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 10px;
  font-size: 13px;
}
.edge-filter label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.edge-filter select,
.edge-filter input {
  padding: 5px 8px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 13px;
}
.edge-filter input {
  width: 180px;
}
.edge-filter button {
  padding: 5px 16px;
  border: 1px solid #185abc;
  background: #185abc;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.log-detail-row td {
  background: #fafafa;
}
.log-head {
  margin: 6px 0 4px;
  font-size: 12px;
  color: #888;
  font-weight: 600;
}
.code {
  background: #f6f8fa;
  border: 1px solid #e3e6ea;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0 0 8px;
  max-height: 220px;
  overflow-y: auto;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.dot-pass {
  background: #1e7e34;
}
.dot-fail {
  background: #c62828;
}
.dot-shadow {
  background: #9e9e9e;
}
.dot-error {
  background: #e65100;
}
.muted {
  color: #666;
}
.error {
  color: #c62828;
}
</style>
