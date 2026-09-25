<script setup lang="ts">
// S15 Task 3 块 I：评审门户——夜间运行（agent_run）的 PR 式评审页。
// 与 Reports（/reports/:deltaId，发版四分类）区分：本页评审的是夜间运行记录。
// 结构：①评审队列（pending 列表，行点击展开 review_output 摘要 + 评审表单）
//      ②已评审列表（decision 徽标 + 评语）。C3：评审决策落库可审计。
import { onMounted, ref } from "vue";
import { createReview, getPendingRuns, getReviews } from "../api";
import type { PendingRun, ReviewDecision, ReviewItem } from "../api";

const pending = ref<PendingRun[]>([]);
const reviews = ref<ReviewItem[]>([]);
const loading = ref(true);
const error = ref("");

// 展开的队列行（同屏只展开一条：评审一次针对一个 run）
const expandedId = ref<number | null>(null);

// 评审表单状态
const reviewer = ref("");
const decision = ref<ReviewDecision | "">("");
const comment = ref("");
const submitting = ref(false);
const submitError = ref("");
const submitHint = ref("");

const DECISION_META: Record<ReviewDecision, { label: string; cls: string }> = {
  approved: { label: "通过", cls: "badge-approved" },
  rejected: { label: "驳回", cls: "badge-rejected" },
  changes_requested: { label: "打回", cls: "badge-changes_requested" },
};

const DECISION_OPTIONS: { value: ReviewDecision; label: string }[] = [
  { value: "approved", label: "通过" },
  { value: "rejected", label: "驳回" },
  { value: "changes_requested", label: "打回" },
];

/** 评审摘要 markdown（无则 null）。夜间图节点名是 review_output；
 * 画布节点 id 是 n1..n5——统一按"output 含 review 字符串键"提取。 */
function reviewMarkdown(run: PendingRun): string | null {
  const seg = run.node_outputs.find(
    (s) => s.node === "review_output" || typeof s.output?.review === "string");
  const review = seg?.output?.review;
  return typeof review === "string" ? review : null;
}

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "");
}

function toggleRun(run: PendingRun): void {
  if (expandedId.value === run.id) {
    expandedId.value = null;
    return;
  }
  expandedId.value = run.id;
  // 换行重置表单：不同 run 的评审互不残留
  reviewer.value = "";
  decision.value = "";
  comment.value = "";
  submitError.value = "";
}

async function loadAll(): Promise<void> {
  // 队列与已评审独立拉取：任一失败只降级自身区块
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

async function submitReview(run: PendingRun): Promise<void> {
  if (!reviewer.value.trim() || !decision.value) {
    submitError.value = "请填写评审人并选择决策";
    return;
  }
  submitting.value = true;
  submitError.value = "";
  try {
    await createReview({
      agent_run_id: run.id,
      reviewer: reviewer.value.trim(),
      decision: decision.value,
      comment: comment.value.trim() || undefined,
    });
    submitHint.value = `已提交评审（run #${run.id}）`;
    expandedId.value = null;
    await loadAll(); // 队列刷新（已评运行消失）+ 已评审列表刷新
  } catch (e) {
    submitError.value = e instanceof Error ? e.message : String(e);
  } finally {
    submitting.value = false;
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
      晨间评审门户：对夜间运行（agent_run）做 PR 式评审——通过 / 驳回 / 打回 + 评语。
      区别于 Reports（发版四分类报告），本页评审的是夜间流水线运行记录。
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
                <form
                  class="review-form"
                  data-testid="review-form"
                  @submit.prevent="submitReview(run)"
                >
                  <label class="form-row">
                    评审人
                    <input
                      v-model="reviewer"
                      type="text"
                      placeholder="你的名字"
                      data-testid="reviewer-input"
                    />
                  </label>
                  <div class="form-row decision-row" role="radiogroup" aria-label="评审决策">
                    <span class="decision-label">决策</span>
                    <label
                      v-for="opt in DECISION_OPTIONS"
                      :key="opt.value"
                      class="decision-option"
                    >
                      <input
                        v-model="decision"
                        type="radio"
                        name="decision"
                        :value="opt.value"
                        :data-testid="`decision-${opt.value}`"
                      />
                      {{ opt.label }}
                    </label>
                  </div>
                  <label class="form-row">
                    评语
                    <textarea
                      v-model="comment"
                      rows="3"
                      placeholder="可选：说明通过/驳回/打回的理由"
                      data-testid="comment-input"
                    ></textarea>
                  </label>
                  <button
                    type="submit"
                    class="btn btn-primary"
                    :disabled="submitting"
                    data-testid="submit-btn"
                  >
                    {{ submitting ? "提交中…" : "提交评审" }}
                  </button>
                  <p v-if="submitError" class="error">{{ submitError }}</p>
                </form>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <p v-if="pending.length" class="muted hint">点击行展开评审摘要与评审表单。</p>
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

    <p v-if="submitHint" class="ok" data-testid="submit-hint">{{ submitHint }}</p>
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
