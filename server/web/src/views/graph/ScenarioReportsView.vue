<script setup lang="ts">
// AR5 场景报告与评审 v2（视觉审查 B 批重做）：
// 四分类色块图例 + tab 分组（待评审/全部）+ 行内评审动作 + 术语统一。
import { computed, onMounted, ref } from "vue";
import { getRunReport, listScenarioReports, reviewReport } from "../../api";
import type { ScenarioReportRow } from "../../api";
import { toastOk, toastErr } from "../../toast";
import { currentUser } from "../../api";

const user = currentUser();
const canReview = computed(() =>
  user?.role === "admin" || user?.role === "reviewer");

const reports = ref<ScenarioReportRow[]>([]);
const loading = ref(true);
const error = ref("");
const tab = ref<"pending" | "all">("pending");

const expandedReport = ref<number | null>(null);
const expandedDetail = ref<ScenarioReportRow["deltas"] | null>(null);
const decision = ref<"approved" | "rejected" | "changes_requested" | "">("");
const comment = ref("");
const submitting = ref(false);

const COVERAGE_LABEL: Record<string, string> = {
  complete: "期望已覆盖",
  partial: "部分覆盖",
  no_expectation: "无期望",
};
const DECISION_LABEL: Record<string, string> = {
  approved: "通过", rejected: "驳回", changes_requested: "打回",
};

const filtered = computed(() => {
  if (tab.value === "pending") {
    return reports.value.filter(r => r.status === "ready"
      && r.review_state !== "reviewed");
  }
  return reports.value;
});

const pendingCount = computed(() =>
  reports.value.filter(r => r.status === "ready"
    && r.review_state !== "reviewed").length);

// 四分类汇总（图例联动——一眼看全局分布）
const quadTotal = computed(() => {
  const t = { expected: 0, missing: 0, unexpected: 0, drift: 0 };
  for (const r of filtered.value) {
    t.expected += r.expected_count;
    t.missing += r.missing_count;
    t.unexpected += r.unexpected_count;
    t.drift += r.drift_count;
  }
  return t;
});

async function toggleReport(reportId: number): Promise<void> {
  if (expandedReport.value === reportId) {
    expandedReport.value = null;
    return;
  }
  expandedReport.value = reportId;
  expandedDetail.value = null;
  decision.value = "";
  comment.value = "";
  try {
    const row = reports.value.find((r) => r.id === reportId);
    if (row) {
      const detail = await getRunReport(row.scenario_run_id);
      expandedDetail.value = detail.deltas;
    }
  } catch {
    expandedDetail.value = [];
  }
}

async function submitReview(reportId: number,
                            preset?: "approved" | "rejected"): Promise<void> {
  const d = preset ?? decision.value;
  if (!d) {
    toastErr("请选择决策");
    return;
  }
  submitting.value = true;
  try {
    await reviewReport(reportId, d, comment.value.trim() || undefined);
    toastOk(`已${DECISION_LABEL[d]}（报告 #${reportId}）`);
    expandedReport.value = null;
    await load();
  } catch (e) {
    toastErr(`评审失败：${e instanceof Error ? e.message : e}`);
  } finally {
    submitting.value = false;
  }
}

function fmtTime(ts: string): string {
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return ts.slice(0, 16).replace("T", " ");
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    reports.value = await listScenarioReports();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section>
    <h1>报告与评审</h1>
    <p class="muted page-desc">
      场景运行终态自动生成的对照报告；待评审的报告在这里完成放行决策。
    </p>

    <!-- 工具行：tab + 四分类图例 -->
    <div class="page-toolbar">
      <div class="tabs" role="tablist">
        <button class="tab" :class="{ active: tab === 'pending' }"
                role="tab" :aria-selected="tab === 'pending'"
                data-testid="tab-pending"
                @click="tab = 'pending'">
          待评审 <span v-if="pendingCount" class="tab-count">{{ pendingCount }}</span>
        </button>
        <button class="tab" :class="{ active: tab === 'all' }"
                role="tab" :aria-selected="tab === 'all'"
                data-testid="tab-all"
                @click="tab = 'all'">全部（{{ reports.length }}）</button>
      </div>
      <span class="spacer"></span>
      <div class="quad-legend" v-if="reports.length" data-testid="quad-legend">
        <span class="quad-chip"><i class="quad-dot expected"></i>期望 <b>{{ quadTotal.expected }}</b></span>
        <span class="quad-chip"><i class="quad-dot missing"></i>缺失 <b>{{ quadTotal.missing }}</b></span>
        <span class="quad-chip"><i class="quad-dot unexpected"></i>意外 <b>{{ quadTotal.unexpected }}</b></span>
        <span class="quad-chip"><i class="quad-dot drift"></i>漂移 <b>{{ quadTotal.drift }}</b></span>
      </div>
    </div>

    <div v-if="loading" class="loading-skeleton">
      <div class="skeleton skeleton-line" style="width: 40%"></div>
      <div class="skeleton skeleton-line"></div>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <div class="block" v-if="filtered.length" data-testid="reports-table-block">
        <table class="tbl" data-testid="scenario-reports-table">
          <thead>
            <tr><th>#</th><th>场景运行</th><th>状态</th><th>覆盖</th>
                <th>四分类</th><th>评审</th><th>时间</th><th v-if="canReview">操作</th></tr>
          </thead>
          <tbody>
            <template v-for="r in filtered" :key="r.id">
              <tr class="row-click" @click="toggleReport(r.id)"
                  :data-testid="`report-${r.id}`">
                <td>#{{ r.id }}</td>
                <td>
                  <RouterLink :to="`/graph/scenario-run/${r.scenario_run_id}`"
                      @click.stop>运行 #{{ r.scenario_run_id }}</RouterLink>
                </td>
                <td>
                  <span class="badge"
                        :class="r.status === 'ready' ? 'badge-pass' : 'badge-error'">
                    {{ r.status === 'ready' ? '就绪' : r.status }}
                  </span>
                </td>
                <td>
                  <span class="badge"
                        :class="r.coverage_state === 'complete' ? 'badge-approved' : 'badge-changes_requested'">
                    {{ COVERAGE_LABEL[r.coverage_state] ?? r.coverage_state }}
                  </span>
                </td>
                <td>
                  <span class="quad-mini" :title="`期望${r.expected_count} 缺失${r.missing_count} 意外${r.unexpected_count} 漂移${r.drift_count}`">
                    <i class="quad-dot expected"></i>{{ r.expected_count }}
                    <i class="quad-dot missing"></i>{{ r.missing_count }}
                    <i class="quad-dot unexpected"></i>{{ r.unexpected_count }}
                    <i class="quad-dot drift"></i>{{ r.drift_count }}
                  </span>
                </td>
                <td>
                  <span v-if="r.review_state === 'reviewed'" class="badge badge-info">已评审</span>
                  <span v-else class="badge badge-candidate">待评审</span>
                </td>
                <td class="muted">{{ fmtTime(r.created_at) }}</td>
                <td v-if="canReview" @click.stop>
                  <template v-if="r.review_state !== 'reviewed' && r.status === 'ready'">
                    <button class="btn btn-sm btn-primary" title="通过该报告"
                            :disabled="submitting"
                            @click="submitReview(r.id, 'approved')">通过</button>
                    <button class="btn btn-sm" title="驳回该报告"
                            :disabled="submitting"
                            @click="submitReview(r.id, 'rejected')">驳回</button>
                  </template>
                </td>
              </tr>
              <tr v-if="expandedReport === r.id" class="panel-row">
                <td :colspan="canReview ? 8 : 7">
                  <div v-if="expandedDetail === null" class="muted">明细加载中…</div>
                  <div v-else-if="!expandedDetail.length" class="muted">
                    无期望绑定明细（{{ r.coverage_state === 'no_expectation' ? '场景未绑定期望——绑定后运行将对照检查' : '' }}）
                  </div>
                  <div v-else class="delta-list">
                    <div v-for="(d, i) in expandedDetail" :key="d.expectation_key"
                         class="delta-item">
                      <b>期望绑定 {{ i + 1 }}</b>
                      <span class="quad-chip"><i class="quad-dot expected"></i>{{ d.expected.length }}</span>
                      <span class="quad-chip"><i class="quad-dot missing"></i>{{ d.missing.length }}</span>
                      <span class="quad-chip"><i class="quad-dot unexpected"></i>{{ d.unexpected.length }}</span>
                      <span class="quad-chip"><i class="quad-dot drift"></i>{{ d.drift.length }}</span>
                      <span class="muted">
                        证据：
                        <RouterLink v-for="rid in d.evidence_replay_run_ids"
                                    :key="rid" :to="`/graph/run/${rid}`"
                                    class="mono">#{{ rid }} </RouterLink>
                      </span>
                    </div>
                  </div>
                  <form v-if="canReview && r.review_state !== 'reviewed' && r.status === 'ready'"
                        class="review-form" data-testid="report-review-form"
                        @submit.prevent="submitReview(r.id)">
                    <div class="decision-row" role="radiogroup" aria-label="评审决策">
                      <label><input v-model="decision" type="radio" name="dec"
                                    value="approved">通过</label>
                      <label><input v-model="decision" type="radio" name="dec"
                                    value="rejected">驳回</label>
                      <label><input v-model="decision" type="radio" name="dec"
                                    value="changes_requested">打回</label>
                    </div>
                    <textarea v-model="comment" rows="2"
                              placeholder="评语（可选）"></textarea>
                    <button type="submit" class="btn btn-primary"
                            :disabled="submitting">提交评审</button>
                  </form>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
      <div v-else class="empty block" data-testid="reports-empty">
        <span class="empty-icon">✓</span>
        <p class="empty-title">{{ tab === 'pending' ? '没有待评审的报告' : '暂无报告' }}</p>
        <p class="empty-sub">
          <template v-if="tab === 'pending' && reports.length">
            全部报告已评审——<a href="#" @click.prevent="tab = 'all'">查看全部 {{ reports.length }} 份</a>
          </template>
          <template v-else>场景运行到终态后自动生成报告</template>
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.row-click { cursor: pointer; }
.row-click:hover { background: var(--color-gray-1); }
.panel-row td { background: var(--color-gray-1); }
.delta-list { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-2); }
.delta-item { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; font-size: 13px; }
.review-form { display: flex; flex-direction: column; gap: var(--space-2); max-width: 480px; }
.decision-row { display: flex; gap: 14px; font-size: 13px; }
.quad-mini { display: inline-flex; align-items: center; gap: 3px; font-size: 12px; font-variant-numeric: tabular-nums; }
.quad-mini .quad-dot { margin-left: 5px; }
.quad-mini .quad-dot:first-child { margin-left: 0; }
.tabs { display: flex; gap: 2px; }
.tab {
  padding: 5px 14px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: var(--radius-md) var(--radius-md) 0 0;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-gray-6);
  cursor: pointer;
}
.tab.active {
  background: var(--color-surface);
  border-color: var(--color-border);
  color: var(--color-gray-8);
  position: relative;
  top: 1px;
}
.tab-count {
  background: var(--color-primary);
  color: #fff;
  border-radius: 999px;
  font-size: 11px;
  padding: 0 6px;
  margin-left: 4px;
}
</style>
