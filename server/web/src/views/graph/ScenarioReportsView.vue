<script setup lang="ts">
// AR5 场景报告与评审：四分类 + 覆盖状态 + 待评审队列同屏。
import { computed, onMounted, ref } from "vue";
import { getPendingReviews, getRunReport, listScenarioReports,
         reviewReport } from "../../api";
import type { PendingReview, ScenarioReportRow } from "../../api";
import { toastOk, toastErr } from "../../toast";
import { currentUser } from "../../api";

const user = currentUser();
const canReview = computed(() =>
  user?.role === "admin" || user?.role === "reviewer");

const reports = ref<ScenarioReportRow[]>([]);
const pending = ref<PendingReview[]>([]);
const loading = ref(true);
const error = ref("");

const expandedReport = ref<number | null>(null);
const expandedDetail = ref<ScenarioReportRow["deltas"] | null>(null);
const decision = ref<"approved" | "rejected" | "changes_requested" | "">("");
const comment = ref("");
const submitting = ref(false);

const COVERAGE_LABEL: Record<string, string> = {
  complete: "期望已覆盖",
  partial: "部分覆盖",
  no_expectation: "无期望覆盖",
};

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

async function submitReview(reportId: number): Promise<void> {
  if (!decision.value) {
    toastErr("请选择决策");
    return;
  }
  submitting.value = true;
  try {
    await reviewReport(reportId, decision.value,
                       comment.value.trim() || undefined);
    toastOk(`已提交评审（报告 #${reportId}）`);
    expandedReport.value = null;
    await load();
  } catch (e) {
    toastErr(`评审失败：${e instanceof Error ? e.message : e}`);
  } finally {
    submitting.value = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    [reports.value, pending.value] = await Promise.all([
      listScenarioReports(), getPendingReviews()]);
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
    <h1>场景报告</h1>
    <p class="muted page-desc">
      场景运行终态自动生成的四分类报告；待评审报告在这里完成放行决策。
    </p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <!-- 待评审队列 -->
      <div class="block" v-if="pending.length" data-testid="pending-reviews">
        <h2>待评审（{{ pending.length }}）</h2>
        <table class="tbl">
          <thead>
            <tr><th>报告</th><th>场景运行</th><th>覆盖</th>
                <th>missing</th><th>unexpected</th><th>drift</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in pending" :key="p.report_id">
              <td>#{{ p.report_id }}</td>
              <td>
                <RouterLink :to="`/graph/scenario-run/${p.scenario_run_id}`">
                  运行 #{{ p.scenario_run_id }}
                </RouterLink>
              </td>
              <td>
                <span class="badge"
                      :class="p.coverage_state === 'complete' ? 'badge-success' : 'badge-changes_requested'">
                  {{ COVERAGE_LABEL[p.coverage_state] ?? p.coverage_state }}
                </span>
              </td>
              <td>{{ p.missing_count }}</td>
              <td>{{ p.unexpected_count }}</td>
              <td>{{ p.drift_count }}</td>
              <td class="muted">{{ p.created_at.replace("T", " ").slice(0, 16) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 报告列表 -->
      <div class="block" v-if="reports.length">
        <h2>全部报告（{{ reports.length }}）</h2>
        <table class="tbl zebra" data-testid="scenario-reports-table">
          <thead>
            <tr><th>#</th><th>场景运行</th><th>状态</th><th>覆盖</th>
                <th>四分类</th><th>评审</th><th>时间</th></tr>
          </thead>
          <tbody>
            <template v-for="r in reports" :key="r.id">
              <tr class="row-click" @click="toggleReport(r.id)"
                  :data-testid="`report-${r.id}`">
                <td>#{{ r.id }}</td>
                <td>
                  <RouterLink :to="`/graph/scenario-run/${r.scenario_run_id}`"
                      @click.stop>运行 #{{ r.scenario_run_id }}</RouterLink>
                </td>
                <td>
                  <span class="badge"
                        :class="r.status === 'ready' ? 'badge-success' : 'badge-error'">
                    {{ r.status }}</span>
                </td>
                <td>{{ COVERAGE_LABEL[r.coverage_state] ?? r.coverage_state }}</td>
                <td class="muted">
                  E{{ r.expected_count }} / M{{ r.missing_count }} /
                  U{{ r.unexpected_count }} / D{{ r.drift_count }}
                </td>
                <td>
                  <span v-if="r.review_state === 'reviewed'" class="badge badge-info">已评审</span>
                  <span v-else class="badge badge-candidate">待评审</span>
                </td>
                <td class="muted">{{ r.created_at.replace("T", " ").slice(0, 16) }}</td>
              </tr>
              <tr v-if="expandedReport === r.id" class="panel-row">
                <td colspan="7">
                  <div v-if="expandedDetail === null" class="muted">明细加载中…</div>
                  <div v-else-if="!expandedDetail.length" class="muted">
                    无期望绑定明细（{{ r.coverage_state === 'no_expectation' ? '场景未绑定期望' : '' }}）
                  </div>
                  <div v-else class="delta-list">
                    <div v-for="(d, i) in expandedDetail" :key="d.expectation_key"
                         class="delta-item">
                      <b>期望绑定 {{ i + 1 }}</b>
                      <span class="chip">expected {{ d.expected.length }}</span>
                      <span class="chip">missing {{ d.missing.length }}</span>
                      <span class="chip">unexpected {{ d.unexpected.length }}</span>
                      <span class="chip">drift {{ d.drift.length }}</span>
                      <span class="muted">
                        证据 run：
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
        暂无场景报告。场景运行到终态后自动生成。
      </div>
    </template>
  </section>
</template>

<style scoped>
.row-click { cursor: pointer; }
.row-click:hover { background: var(--color-gray-1); }
.panel-row td { background: var(--color-gray-1); }
.delta-list { display: flex; flex-direction: column; gap: var(--space-2); margin-bottom: var(--space-2); }
.delta-item { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; font-size: 13px; }
.review-form { display: flex; flex-direction: column; gap: var(--space-2); max-width: 480px; }
.decision-row { display: flex; gap: 14px; font-size: 13px; }
</style>
