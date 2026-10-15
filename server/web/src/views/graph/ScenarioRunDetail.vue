<script setup lang="ts">
// AR5 场景运行详情：聚合状态 + 步骤/子 ReplayRun + 自动报告链接。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getScenario, getScenarioRun } from "../../api";
import type { ScenarioDetail, ScenarioRunDetail } from "../../api";

const route = useRoute();
const run = ref<ScenarioRunDetail | null>(null);
const scenario = ref<ScenarioDetail | null>(null);
const loading = ref(true);
const error = ref("");

const STATUS_TONE: Record<string, string> = {
  pass: "badge-success", fail: "badge-fail", error: "badge-error",
  shadow: "badge-shadow", aborted: "badge-candidate",
  running: "badge-queued", queued: "badge-queued",
};
const STATUS_LABEL: Record<string, string> = {
  pass: "通过", fail: "失败", error: "异常", shadow: "预演",
  aborted: "已中止", running: "运行中", queued: "排队中",
};

const runId = computed(() => String(route.params.runId));

function fmtTime(ts: string | null): string {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 19);
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    run.value = await getScenarioRun(runId.value);
    try {
      scenario.value = await getScenario(run.value.scenario_id);
    } catch { scenario.value = null; }
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
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <template v-else-if="run">
      <!-- 面包屑：场景 ← 运行（审查：深链页位置感断裂） -->
      <nav class="breadcrumb" aria-label="面包屑">
        <RouterLink to="/graph/scenario-runs">场景运行</RouterLink>
        <span class="crumb-sep">/</span>
        <RouterLink :to="`/graph/scenario/${run.scenario_id}`">
          {{ scenario?.name ?? `场景 #${run.scenario_id}` }}
        </RouterLink>
        <span class="crumb-sep">/</span>
        <span>#{{ run.id }}</span>
      </nav>

      <h1>{{ scenario?.name ?? "场景运行" }} <span class="h1-id">#{{ run.id }}</span></h1>
      <p class="muted page-desc">
        定义 v{{ run.definition_snapshot?.root?.definition_version ?? "?" }}
        · {{ run.executor === "server" ? "服务端" : "插件" }}执行
        · {{ run.mode === "shadow" ? "预演" : "执行" }}
        · {{ fmtTime(run.started_at) }} → {{ fmtTime(run.finished_at) }}
      </p>

      <div class="run-head">
        <span class="badge" :class="STATUS_TONE[run.status] || 'badge-info'"
              data-testid="run-status">{{ STATUS_LABEL[run.status] ?? run.status }}</span>
        <span class="muted">
          通过 {{ run.pass_count }} / 失败 {{ run.fail_count }} /
          异常 {{ run.error_count }} / 预演 {{ run.shadow_count }} /
          未执行 {{ run.blocked_count }} · 共 {{ run.total_count }} 步
        </span>
        <RouterLink to="/graph/scenario-reports" class="btn btn-secondary">
          查看报告
        </RouterLink>
      </div>

      <div class="block">
        <h2>步骤执行（{{ run.runs.length }}）</h2>
        <p v-if="!run.runs.length" class="muted">
          无子运行记录（服务端预演短路或执行前中止）。
        </p>
        <table v-else class="tbl" data-testid="run-children">
          <thead>
            <tr><th>#</th><th>子运行</th><th>技能</th><th>状态</th>
                <th>重试</th><th>失败类</th><th>耗时</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in run.runs" :key="c.id">
              <td>{{ (c.execution_index ?? 0) + 1 }}</td>
              <td>
                <RouterLink :to="`/graph/run/${c.id}`" class="mono">#{{ c.id }}</RouterLink>
              </td>
              <td>
                <RouterLink :to="`/graph/skill/${c.skill_id}`">#{{ c.skill_id }}</RouterLink>
              </td>
              <td>
                <span class="dot" :class="`dot-${c.status === 'pass' ? 'pass' : c.status === 'fail' ? 'fail' : 'shadow'}`"></span>
                {{ c.status }}
              </td>
              <td class="muted">{{ c.attempt }}</td>
              <td v-if="c.failure_class">
                <span class="badge badge-fail">{{ c.failure_class }}</span>
              </td>
              <td v-else class="muted">—</td>
              <td class="muted">
                {{ c.duration_ms ? (c.duration_ms / 1000).toFixed(1) + 's' : '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.breadcrumb {
  font-size: 12.5px;
  margin-bottom: var(--space-1);
  color: var(--color-text-secondary);
}
.breadcrumb a {
  color: var(--color-text-secondary);
  text-decoration: none;
}
.breadcrumb a:hover {
  color: var(--color-primary);
}
.crumb-sep {
  margin: 0 6px;
  color: var(--color-gray-4);
}
.h1-id {
  font-size: 15px;
  font-weight: 600;
  color: var(--color-gray-5);
}
.run-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-2) 0;
}
</style>
