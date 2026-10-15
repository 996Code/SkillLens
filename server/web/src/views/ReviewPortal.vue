<script setup lang="ts">
// AR1：评审门户冻结为只读（AgentRun 评审写入已 410）。AR4 将评审对象
// 统一为场景报告；本页保留历史评审与待评运行审计视图。
import { onMounted, ref } from "vue";
import { getPendingRuns, getReviews } from "../api";
import type { PendingRun, ReviewDecision, ReviewItem } from "../api";
import { fmtTime } from "../run-format";

const DECISION_META: Record<ReviewDecision, { label: string; cls: string }> = {
  approved: { label: "通过", cls: "badge-approved" },
  rejected: { label: "驳回", cls: "badge-rejected" },
  changes_requested: { label: "打回", cls: "badge-changes_requested" },
};

const pending = ref<PendingRun[]>([]);
const reviews = ref<ReviewItem[]>([]);
const loading = ref(true);
const error = ref("");

const expandedId = ref<number | null>(null);

/** 评审摘要 markdown（无则 null）。夜间图节点名是 review_output；
 * 画布节点 id 是 n1..n5——统一按"output 含 review 字符串键"提取。 */
function reviewMarkdown(run: PendingRun): string | null {
  const seg = run.node_outputs.find(
    (s) => s.node === "review_output" || typeof s.output?.review === "string");
  const review = seg?.output?.review;
  return typeof review === "string" ? review : null;
}

function toggleRun(run: PendingRun): void {
  expandedId.value = expandedId.value === run.id ? null : run.id;
}

async function loadAll(): Promise<void> {
  try {
    pending.value = await getPendingRuns();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
  try {
    reviews.value = await getReviews();
  } catch {
    /* 已评审列表失败容忍：队列仍可用 */
  }
}

onMounted(async () => {
  await loadAll();
  loading.value = false;
});
</script>

<template>
  <section>
    <h1>评审</h1>
    <p class="muted page-desc">
      历史评审审计视图（AR1 起只读）：夜间运行记录与既往评审决策可查；
      场景运行报告评审将在 AR4 上线。
    </p>

    <!-- ① 评审队列 -->
    <div class="block">
      <h2>评审队列</h2>
      <p v-if="loading" class="muted">加载中…</p>
      <p v-else-if="error" class="error">加载失败：{{ error }}</p>
      <div
        v-else-if="pending.length === 0"
        class="empty"
        data-testid="pending-empty"
      >
        <span class="empty-icon">☾</span>
        <p class="empty-title">夜间无待评审运行</p>
        <p class="empty-sub">夜间流水线结束后，待评审运行会出现在这里</p>
      </div>
      <table v-else class="tbl" data-testid="pending-table">
        <thead>
          <tr>
            <th>运行</th><th>图</th><th>状态</th><th>开始时间</th><th>评审摘要</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="run in pending" :key="run.id">
            <tr
              class="row-click"
              :class="{ 'row-selected': expandedId === run.id }"
              :data-id="run.id"
              data-testid="pending-row"
              @click="toggleRun(run)"
            >
              <td>#{{ run.id }}</td>
              <td class="mono">{{ run.graph_name }}</td>
              <td><span class="chip chip-kind">{{ run.status }}</span></td>
              <td>{{ fmtTime(run.started_at) }}</td>
              <td>
                <span
                  v-if="reviewMarkdown(run)"
                  class="badge badge-has-review"
                  data-testid="has-review"
                >含评审摘要</span>
                <span v-else class="muted">—</span>
              </td>
            </tr>
            <tr v-if="expandedId === run.id" class="panel-row">
              <td colspan="5">
                <pre
                  v-if="reviewMarkdown(run)"
                  class="code"
                  data-testid="review-markdown"
                >{{ reviewMarkdown(run) }}</pre>
                <p class="hint" data-testid="frozen-hint">
                  AgentRun 评审写入已冻结（AR1）；AR4 起评审对象为场景报告
                </p>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-if="pending.length" class="muted hint">点击行展开评审摘要。</p>
    </div>

    <!-- ② 已评审 -->
    <div class="block">
      <h2>已评审</h2>
      <p v-if="loading" class="muted">加载中…</p>
      <p v-else-if="reviews.length === 0" class="muted empty-line">暂无评审记录</p>
      <table v-else class="tbl zebra" data-testid="reviewed-table">
        <thead>
          <tr>
            <th>#</th><th>运行</th><th>图</th><th>状态</th>
            <th>评审人</th><th>决策</th><th>评语</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reviews" :key="r.id">
            <td>#{{ r.id }}</td>
            <td>#{{ r.agent_run_id }}</td>
            <td class="mono">{{ r.agent_run?.graph_name || "—" }}</td>
            <td>{{ r.agent_run?.status || "—" }}</td>
            <td>{{ r.reviewer }}</td>
            <td>
              <span
                class="badge"
                :class="DECISION_META[r.decision]?.cls"
                data-testid="decision-badge"
              >{{ DECISION_META[r.decision]?.label || r.decision }}</span>
            </td>
            <td>{{ r.comment || "—" }}</td>
            <td>{{ fmtTime(r.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

  </section>
</template>

<style scoped>
/* S16 块 Q：表格/徽标/chip/代码块/分区块卡片走全局令牌类，这里只留布局差异 */
.hint {
  font-size: 12px;
  margin: var(--space-1) 0 0;
}
.empty-line {
  margin: var(--space-2) 0;
}
.row-click {
  cursor: pointer;
}
.row-selected,
.row-selected:hover {
  background: var(--color-primary-soft);
}
.panel-row td {
  background: var(--color-gray-1);
}
/* 评审摘要 markdown：覆盖全局 .code 排布 */
.code {
  margin: 0 0 10px;
  max-height: 220px;
  overflow-y: auto;
}
.review-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 520px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: 13px;
}
.decision-row {
  flex-direction: row;
  align-items: center;
  gap: 14px;
}
.decision-label {
  font-size: 13px;
}
.decision-option {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 13px;
  cursor: pointer;
}
.review-form button {
  align-self: flex-start;
}
</style>
