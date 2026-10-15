<script setup lang="ts">
// AR5 场景运行列表 v2（视觉审查 B 批）：汇总工具行 + 耗时列 +
// 术语统一（状态/执行端/模式中文）+ 时间相对化。
import { computed, onMounted, ref } from "vue";
import { listScenarioRuns, listScenarios } from "../../api";
import type { ScenarioRunRow, ScenarioListItem } from "../../api";

const runs = ref<ScenarioRunRow[]>([]);
const scenarios = ref<Record<number, ScenarioListItem>>({});
const loading = ref(true);
const error = ref("");
const statusFilter = ref("");

const STATUS_TONE: Record<string, string> = {
  pass: "badge-success", fail: "badge-fail", error: "badge-error",
  shadow: "badge-shadow", aborted: "badge-candidate",
  running: "badge-queued", queued: "badge-queued",
};
const STATUS_LABEL: Record<string, string> = {
  pass: "通过", fail: "失败", error: "异常", shadow: "预演完成",
  aborted: "已中止", running: "运行中", queued: "排队中",
};

const filtered = computed(() => {
  const q = statusFilter.value;
  return q ? runs.value.filter((r) => r.status === q) : runs.value;
});

// 汇总（工具行承接——空白页头重脚轻的解法）
const summary = computed(() => {
  const terminal = filtered.value.filter(
    (r) => !["queued", "running"].includes(r.status));
  const pass = terminal.filter((r) => r.status === "pass").length;
  return {
    total: filtered.value.length,
    terminal: terminal.length,
    pass,
    rate: terminal.length
      ? Math.round((pass / terminal.length) * 100) : null,
  };
});

function scenarioName(id: number): string {
  return scenarios.value[id]?.name ?? `场景 #${id}`;
}

function fmtDuration(r: ScenarioRunRow): string {
  if (!r.started_at || !r.finished_at) return "—";
  const ms = new Date(r.finished_at).getTime()
    - new Date(r.started_at).getTime();
  if (ms < 0) return "—";
  const s = ms / 1000;
  if (s >= 60) {
    const m = Math.floor(s / 60);
    return `${m}m${Math.round(s - m * 60)}s`;
  }
  return `${s.toFixed(s < 1 ? 2 : 1)}s`;
}

function fmtTime(ts: string | null): string {
  if (!ts) return "—";
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
    const [rows, scs] = await Promise.all([listScenarioRuns(), listScenarios("", "active")]);
    let all = scs;
    if (rows.some((r) => !scs.find((s) => s.id === r.scenario_id))) {
      try { all = await listScenarios(); } catch { /* active 兜底 */ }
    }
    scenarios.value = Object.fromEntries(all.map((s) => [s.id, s]));
    runs.value = rows;
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
    <h1>场景运行</h1>
    <p class="muted page-desc">
      按测试场景聚合的运行记录：一次场景执行关联全部步骤证据与自动报告。
    </p>

    <div class="page-toolbar">
      <select v-model="statusFilter" aria-label="状态过滤" data-testid="runs-status-filter">
        <option value="">全部状态</option>
        <option v-for="(label, s) in STATUS_LABEL" :key="s" :value="s">{{ label }}</option>
      </select>
      <span class="spacer"></span>
      <span class="summary" v-if="filtered.length" data-testid="runs-summary">
        {{ filtered.length }} 次运行
        <template v-if="summary.rate !== null">
          · 已完成 {{ summary.terminal }} 次中通过 {{ summary.pass }}（{{ summary.rate }}%）
        </template>
      </span>
    </div>

    <div v-if="loading" class="loading-skeleton"><div class="skeleton skeleton-line" style="width: 40%"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line" style="width: 70%"></div></div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="!filtered.length" class="empty block" data-testid="scenario-runs-empty">
      暂无场景运行。从测试场景详情点「运行场景」开始。
    </div>

    <div v-else class="block">
      <table class="tbl zebra" data-testid="scenario-runs-table">
        <thead>
          <tr>
            <th>#</th><th>场景</th><th>状态</th><th>通过</th>
            <th>执行端</th><th>模式</th><th>耗时</th><th>时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id"
              :data-testid="`scenario-run-${r.id}`">
            <td>
              <RouterLink :to="`/graph/scenario-run/${r.id}`">#{{ r.id }}</RouterLink>
            </td>
            <td>
              <RouterLink :to="`/graph/scenario/${r.scenario_id}`">
                {{ scenarioName(r.scenario_id) }}
              </RouterLink>
            </td>
            <td>
              <span class="badge" :class="STATUS_TONE[r.status] || ''"
                    :data-testid="`run-status-${r.id}`">
                {{ STATUS_LABEL[r.status] ?? r.status }}
              </span>
            </td>
            <td class="mono">{{ r.pass_count }}/{{ r.total_count }}</td>
            <td class="muted">{{ r.executor === "server" ? "服务端" : "插件" }}</td>
            <td class="muted">{{ r.mode === "shadow" ? "预演" : "执行" }}</td>
            <td class="mono">{{ fmtDuration(r) }}</td>
            <td class="muted">{{ fmtTime(r.finished_at || r.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
