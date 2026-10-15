<script setup lang="ts">
// AR5 场景运行列表：ScenarioRun 口径的运行历史（用户工作层）。
// 时间线（Skill run 粒度）保留为下钻视图。
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
  running: "badge-info", queued: "badge-info",
};

const filtered = computed(() => {
  const q = statusFilter.value;
  return q ? runs.value.filter((r) => r.status === q) : runs.value;
});

function scenarioName(id: number): string {
  return scenarios.value[id]?.name ?? `场景 #${id}`;
}

function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 19);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [rows, scs] = await Promise.all([listScenarioRuns(), listScenarios("", "active")]);
    // archived 场景的运行也要能显示名字——再拉一次全量状态
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

    <div class="toolbar">
      <select v-model="statusFilter" aria-label="状态过滤" data-testid="runs-status-filter">
        <option value="">全部状态</option>
        <option v-for="s in ['pass','fail','error','shadow','aborted']"
                :key="s" :value="s">{{ s }}</option>
      </select>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="!filtered.length" class="empty block" data-testid="scenario-runs-empty">
      暂无场景运行。从测试场景详情点「运行场景」开始。
    </div>

    <div v-else class="block">
      <table class="tbl zebra" data-testid="scenario-runs-table">
        <thead>
          <tr>
            <th>#</th><th>场景</th><th>状态</th><th>执行端</th>
            <th>通过</th><th>模式</th><th>开始</th><th>结束</th>
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
              <span class="badge" :class="STATUS_TONE[r.status] || ''">{{ r.status }}</span>
            </td>
            <td class="muted">{{ r.executor }}</td>
            <td>{{ r.pass_count }}/{{ r.total_count }}</td>
            <td class="muted">{{ r.mode }}</td>
            <td class="muted">{{ fmtTime(r.started_at) }}</td>
            <td class="muted">{{ fmtTime(r.finished_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
</style>
