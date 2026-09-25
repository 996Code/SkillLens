<script setup lang="ts">
// Task 4（S9 块C）：四分类报告页——GET /reports/{id}（四分类）+
// GET /expected-deltas/{expected_delta_id}（需求上下文）。
// 只读：无报告列表入口，空 delta 时用输入框查询。
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getExpectedDelta, getLinkedDiscoveries, getReport } from "../api";
import type { DeltaItem, DiscoveredFeatureItem, ExpectedDelta, Report } from "../api";

const route = useRoute();
const router = useRouter();

const report = ref<Report | null>(null);
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

async function load(id: string | number) {
  loading.value = true;
  notFound.value = false;
  error.value = "";
  report.value = null;
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
      <button type="submit">查询</button>
    </form>

    <p v-if="loading" class="muted">加载中…</p>

    <!-- 空 delta 引导 -->
    <p v-else-if="!route.params.deltaId" class="muted">
      输入 report id 查询四分类报告（报告由 observe → report 流程生成）。
    </p>

    <div v-else-if="notFound" class="empty">
      <p>报告不存在（id={{ route.params.deltaId }}）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="report">
      <!-- 需求上下文 -->
      <div v-if="expectedDelta" class="ctx">
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
          <span class="badge-linked">已发现实现 ×{{ linkedDiscoveries.length }}</span>
          <ul class="linked-list">
            <li v-for="d in linkedDiscoveries" :key="d.id" class="mono">
              {{ d.api_template || d.anchor_label }}
            </li>
          </ul>
        </div>
      </div>

      <!-- 四栏 -->
      <div class="quad">
        <div v-for="col in columns" :key="col.key" class="qcol" :class="col.cls">
          <h3>{{ col.label }} <span class="count">{{ col.items.length }}</span></h3>
          <p v-if="col.items.length === 0" class="muted">（空）</p>
          <ul v-else>
            <li v-for="(item, i) in col.items" :key="i">
              <span class="chip chip-type">{{ item.type }}</span>
              <span class="mono value">{{ item.value }}</span>
            </li>
          </ul>
        </div>
      </div>

      <p class="muted footer">
        report #{{ report.id }} · observed_delta #{{ report.observed_delta_id }}
        · 生成于 {{ fmtTime(report.created_at) }}
      </p>
    </template>
  </section>
</template>

<style scoped>
.query {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.query input {
  width: 200px;
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
}
.query button {
  padding: 6px 16px;
  border: 1px solid #185abc;
  background: #185abc;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
.ctx {
  margin-bottom: 20px;
}
.ctx h2 {
  font-size: 16px;
  border-bottom: 1px solid #eee;
  padding-bottom: 6px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
  margin: 8px 0;
}
.meta dt {
  font-size: 12px;
  color: #888;
}
.meta dd {
  margin: 2px 0 0;
}
.changes {
  margin: 4px 0 0;
  padding-left: 20px;
  font-size: 13px;
}
.changes li {
  margin-bottom: 4px;
}
.linked {
  margin-top: 10px;
}
.badge-linked {
  display: inline-block;
  font-size: 12px;
  color: #1b5e20;
  background: #e8f5e9;
  border: 1px solid #a5d6a7;
  border-radius: 10px;
  padding: 1px 10px;
}
.linked-list {
  margin: 6px 0 0;
  padding-left: 20px;
  font-size: 13px;
}
.linked-list li {
  margin-bottom: 2px;
}
.quad {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 14px;
}
.qcol {
  border: 1px solid #e3e6ea;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}
.qcol h3 {
  margin: 0 0 8px;
  font-size: 14px;
  border-bottom: 2px solid transparent;
  padding-bottom: 6px;
}
.count {
  display: inline-block;
  min-width: 20px;
  text-align: center;
  border-radius: 10px;
  font-size: 12px;
  padding: 0 6px;
  color: #fff;
  background: #999;
}
.col-expected h3 {
  border-color: #185abc;
}
.col-expected .count {
  background: #185abc;
}
.col-missing h3 {
  border-color: #c62828;
}
.col-missing .count {
  background: #c62828;
}
.col-unexpected h3 {
  border-color: #e65100;
}
.col-unexpected .count {
  background: #e65100;
}
.col-drift h3 {
  border-color: #9e9e9e;
}
.col-drift .count {
  background: #9e9e9e;
}
.qcol ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.qcol li {
  padding: 6px 0;
  border-bottom: 1px dashed #eee;
  font-size: 13px;
}
.qcol li:last-child {
  border-bottom: none;
}
.chip-type {
  display: inline-block;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  background: #eef2f7;
  border-radius: 4px;
  padding: 0 6px;
  margin-right: 6px;
}
.value {
  word-break: break-all;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
}
.footer {
  margin-top: 16px;
  font-size: 12px;
}
.muted {
  color: #666;
}
.error {
  color: #c62828;
}
.empty p {
  color: #666;
}
</style>
