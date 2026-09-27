<script setup lang="ts">
// Task 4（S9 块C）：四分类报告页——GET /reports/{id}（四分类）+
// GET /expected-deltas/{expected_delta_id}（需求上下文）。
// 只读：无报告列表入口，空 delta 时用输入框查询。
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  getExpectedDelta,
  getLinkedDiscoveries,
  getReport,
  getReportPerf,
} from "../api";
import type {
  DeltaItem,
  DiscoveredFeatureItem,
  ExpectedDelta,
  PerfContext,
  Report,
} from "../api";

const route = useRoute();
const router = useRouter();

const report = ref<Report | null>(null);
// S23 块 V：性能上下文（基线/当前/趋势），失败不阻塞四分类展示
const perf = ref<PerfContext | null>(null);
const expectedDelta = ref<ExpectedDelta | null>(null);
const linkedDiscoveries = ref<DiscoveredFeatureItem[]>([]);
const loading = ref(false);
const notFound = ref(false);
const error = ref("");
const queryId = ref(String(route.params.deltaId ?? ""));

const columns = computed(() => {
  const r = report.value;
  if (!r) return [];
  return [
    { key: "expected", label: "expected（符合预期）", cls: "col-expected",
      items: r.expected },
    { key: "missing", label: "missing（期望未发生）", cls: "col-missing",
      items: r.missing },
    { key: "unexpected", label: "unexpected（意外发生）", cls: "col-unexpected",
      items: r.unexpected },
    { key: "drift", label: "drift（漂移）", cls: "col-drift",
      items: r.drift },
  ];
});

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "");
}

/** S23 块 V：趋势条高度（2-40px，按历史最大值归一）。 */
function trendHeight(ms: number): number {
  const hist = perf.value?.history_ms ?? [];
  const max = Math.max(...hist, perf.value?.current_ms ?? 0, ms, 1);
  return Math.max(2, Math.round((ms / max) * 40));
}

async function load(id: string | number) {
  loading.value = true;
  notFound.value = false;
  error.value = "";
  report.value = null;
  perf.value = null;
  expectedDelta.value = null;
  linkedDiscoveries.value = [];
  try {
    report.value = await getReport(id);
    // 需求上下文：报告行带 expected_delta_id，失败不阻塞四分类展示
    try {
      expectedDelta.value = await getExpectedDelta(report.value.expected_delta_id);
    } catch {
      /* expected delta 可能已删，四分类仍可评审 */
    }
    // S12 N2：已发现实现（confirm 时对齐到该 delta 的 discovery），失败不阻塞
    try {
      linkedDiscoveries.value = await getLinkedDiscoveries(
        report.value.expected_delta_id);
    } catch {
      /* discoveries 端点异常时徽标隐藏 */
    }
    // S23 块 V：性能上下文（旧报告无 duration 数据时 median=null，区块自适应）
    try {
      perf.value = await getReportPerf(id);
    } catch {
      /* perf 端点异常时区块隐藏 */
    }
  } catch (e) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      notFound.value = true;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
}

function submitQuery() {
  const id = queryId.value.trim();
  if (!id || !/^\d+$/.test(id)) return;
  router.push(`/reports/${id}`);
}

onMounted(() => {
  const id = String(route.params.deltaId ?? "");
  if (id && /^\d+$/.test(id)) {
    void load(id);
  }
});

watch(() => route.params.deltaId, (v) => {
  const id = String(v ?? "");
  if (id && /^\d+$/.test(id)) {
    queryId.value = id;
    void load(id);
  }
});
</script>

<template>
  <section>
    <h1>四分类报告</h1>

    <!-- 查询框：暂无报告列表入口，按 id 查 -->
    <form class="query" @submit.prevent="submitQuery">
      <input
        v-model="queryId"
        type="text"
        inputmode="numeric"
        placeholder="输入 report id"
        aria-label="report id"
      />
      <button type="submit" class="btn btn-primary">查询</button>
    </form>

    <p v-if="loading" class="muted">加载中…</p>

    <!-- 空 delta 引导 -->
    <p v-else-if="!route.params.deltaId" class="muted">
      输入 report id 查询四分类报告（报告由 observe → report 流程生成）。
    </p>

    <div v-else-if="notFound" class="empty">
      <span class="empty-icon">∅</span>
      <p class="empty-title">报告不存在</p>
      <p class="empty-sub">id={{ route.params.deltaId }}——报告可能尚未生成，先走 observe → report 流程。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="report">
      <!-- 需求上下文（S16 块 Q：卡片化） -->
      <div v-if="expectedDelta" class="ctx block">
        <h2>需求上下文</h2>
        <dl class="meta">
          <div><dt>requirement</dt><dd class="mono">{{ expectedDelta.requirement_id }}</dd></div>
          <div><dt>feature</dt><dd>{{ expectedDelta.feature || "—" }}</dd></div>
          <div><dt>status</dt><dd>{{ expectedDelta.status }}</dd></div>
          <div><dt>reviewed_by</dt><dd>{{ expectedDelta.reviewed_by || "—" }}</dd></div>
        </dl>
        <ol v-if="expectedDelta.changes.length" class="changes">
          <li v-for="(c, i) in expectedDelta.changes" :key="i">
            <span class="chip chip-type">{{ c.type }}</span>
            <span class="mono">{{ c.value }}</span>
          </li>
        </ol>
        <!-- S12 N2：已发现实现——confirm 时对齐到该 delta 的 discovery（模板/锚点） -->
        <div v-if="linkedDiscoveries.length" class="linked">
          <span class="badge badge-success">已发现实现 ×{{ linkedDiscoveries.length }}</span>
          <ul class="linked-list">
            <li v-for="d in linkedDiscoveries" :key="d.id" class="mono">
              {{ d.api_template || d.anchor_label }}
            </li>
          </ul>
        </div>
      </div>

      <!-- S16 块 Q：四分类统计卡（大数字 + 标签）置顶 -->
      <div class="stats">
        <div v-for="col in columns" :key="col.key" class="stat-card" :class="col.cls">
          <span class="stat-num count">{{ col.items.length }}</span>
          <span class="stat-label">{{ col.label }}</span>
        </div>
      </div>

      <!-- 四栏明细列表 -->
      <div class="quad">
        <div v-for="col in columns" :key="col.key" class="qcol" :class="col.cls">
          <h3>{{ col.label }}</h3>
          <p v-if="col.items.length === 0" class="muted">（空）</p>
          <ul v-else>
            <li v-for="(item, i) in col.items" :key="i">
              <span class="chip chip-type">{{ item.type }}</span>
              <span class="mono value">{{ item.value }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- S23 块 V：性能漂移区块（有基线数据才渲染） -->
      <div
        v-if="perf?.baseline?.median"
        class="perf-block"
        data-testid="perf-block"
      >
        <h3>性能基线</h3>
        <dl class="meta">
          <div><dt>基线中位数</dt><dd class="mono">{{ perf.baseline.median }}ms（{{ perf.baseline.n }} 次）</dd></div>
          <div><dt>本次回放</dt><dd class="mono">{{ perf.current_ms ?? "—" }}ms</dd></div>
        </dl>
        <div class="perf-trend" data-testid="perf-trend">
          <span
            v-for="(ms, i) in perf.history_ms"
            :key="i"
            class="perf-bar"
            :style="{ height: trendHeight(ms) + 'px' }"
            :title="`${ms}ms`"
          ></span>
          <span
            v-if="perf.current_ms"
            class="perf-bar perf-bar-current"
            :style="{ height: trendHeight(perf.current_ms) + 'px' }"
            :title="`本次 ${perf.current_ms}ms`"
          ></span>
        </div>
        <p class="muted">趋势：最近 {{ perf.history_ms.length }} 次回放耗时（右端亮色为本次）</p>
      </div>

      <p class="muted footer">
        report #{{ report.id }} · observed_delta #{{ report.observed_delta_id }}
        · 生成于 {{ fmtTime(report.created_at) }}
      </p>
    </template>
  </section>
</template>

<style scoped>
/* S16 块 Q：表格/徽标/chip 走全局类，这里只留布局与四分类分色 */
.query {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.query input {
  width: 200px;
}
.ctx {
  margin-bottom: var(--space-4);
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
  margin: var(--space-2) 0;
}
.meta dt {
  font-size: 12px;
  color: var(--color-gray-5);
}
.meta dd {
  margin: 2px 0 0;
}
.changes {
  margin: var(--space-1) 0 0;
  padding-left: 20px;
  font-size: 13px;
}
.changes li {
  margin-bottom: var(--space-1);
}
.linked {
  margin-top: 10px;
}
.linked-list {
  margin: var(--space-1) 0 0;
  padding-left: 20px;
  font-size: 13px;
}
.linked-list li {
  margin-bottom: 2px;
}
/* S23 块 V：性能基线区块 */
.perf-block {
  margin-top: 24px;
  padding: 16px;
  border: 1px solid var(--color-border, #e0e0e0);
  border-radius: 8px;
  background: #fafafa;
}
.perf-block h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.perf-trend {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 44px;
  margin: 10px 0 4px;
}
.perf-bar {
  width: 10px;
  background: #9aa4b2;
  border-radius: 2px 2px 0 0;
}
.perf-bar-current {
  background: var(--color-primary, #2563eb);
}
/* 四分类统计卡：4 色（expected=主色 / missing=危险 / unexpected=警告 / drift=中性）*/
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-top: 3px solid var(--color-gray-4);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-num {
  font-size: 30px;
  font-weight: 700;
  line-height: 1.1;
}
.stat-label {
  font-size: 12px;
  color: var(--color-text-secondary);
}
.stat-card.col-expected {
  border-top-color: var(--color-primary);
}
.stat-card.col-expected .stat-num {
  color: var(--color-primary);
}
.stat-card.col-missing {
  border-top-color: var(--color-danger);
}
.stat-card.col-missing .stat-num {
  color: var(--color-danger);
}
.stat-card.col-unexpected {
  border-top-color: var(--color-warning);
}
.stat-card.col-unexpected .stat-num {
  color: var(--color-warning);
}
.stat-card.col-drift {
  border-top-color: var(--color-gray-5);
}
.stat-card.col-drift .stat-num {
  color: var(--color-gray-6);
}
/* 明细四栏 */
.quad {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-3);
}
.qcol {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-3) var(--space-4);
}
.qcol h3 {
  margin: 0 0 var(--space-2);
  font-size: 13px;
  color: var(--color-gray-7);
  border-bottom: 2px solid transparent;
  padding-bottom: var(--space-1);
}
.qcol.col-expected h3 {
  border-color: var(--color-primary);
}
.qcol.col-missing h3 {
  border-color: var(--color-danger);
}
.qcol.col-unexpected h3 {
  border-color: var(--color-warning);
}
.qcol.col-drift h3 {
  border-color: var(--color-gray-5);
}
.qcol ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.qcol li {
  padding: var(--space-1) 0;
  border-bottom: 1px dashed var(--color-gray-3);
  font-size: 13px;
}
.qcol li:last-child {
  border-bottom: none;
}
.value {
  word-break: break-all;
}
.footer {
  margin-top: var(--space-4);
  font-size: 12px;
}
</style>
