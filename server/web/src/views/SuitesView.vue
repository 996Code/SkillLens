<script setup lang="ts">
// AR1：legacy 流程分组只读视图。Suite 写入/执行已冻结（服务端 410），
// 业务入口统一走测试场景；本页保留历史审计（迁移决策+执行历史）。
import { onMounted, ref } from "vue";
import { listSuiteRuns, listSuites } from "../api";
import type { SuiteItem, SuiteRunSummary } from "../api";

const suites = ref<SuiteItem[]>([]);
const loading = ref(true);
const error = ref("");

const historySuiteId = ref<number | null>(null);
const history = ref<SuiteRunSummary[]>([]);
const historyLoading = ref(false);
const historyError = ref("");

async function showHistory(id: number): Promise<void> {
  if (historySuiteId.value === id) {
    historySuiteId.value = null;
    return;
  }
  historySuiteId.value = id;
  history.value = [];
  historyError.value = "";
  historyLoading.value = true;
  try {
    history.value = await listSuiteRuns(id);
  } catch (e) {
    history.value = [];
    historyError.value = e instanceof Error ? e.message : String(e);
  } finally {
    historyLoading.value = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    suites.value = await listSuites();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section>
    <h1>流程分组（legacy）</h1>
    <p class="muted page-desc">
      旧版分组已冻结为只读审计。新的业务流程组合请在
      <RouterLink to="/graph/scenarios">测试场景</RouterLink> 中创建和执行。
    </p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="suites.length === 0" class="empty block">
      无历史分组。
    </div>

    <div v-for="s in suites" :key="s.id" class="block suite-card">
      <div class="suite-head">
        <h2>{{ s.name }}</h2>
        <span class="muted">{{ s.skills.length }} 个自动化流程</span>
        <span v-if="s.scenario_id" class="badge badge-info">
          已映射场景 #{{ s.scenario_id }}
        </span>
        <span v-else-if="s.migration_status" class="badge badge-changes_requested">
          {{ s.migration_status }}
        </span>
        <button class="btn btn-secondary" @click="showHistory(s.id)">
          执行历史
        </button>
      </div>
      <p v-if="s.migration_reason" class="muted">{{ s.migration_reason }}</p>
      <ul class="suite-skills">
        <li v-for="sk in s.skills" :key="sk.id">
          <RouterLink :to="`/graph/skill/${sk.id}`">{{ sk.name }}</RouterLink>
        </li>
      </ul>
    </div>

    <div v-if="historySuiteId !== null" class="block" data-testid="suite-history">
      <h2>执行历史</h2>
      <p v-if="historyLoading" class="muted">加载中…</p>
      <p v-else-if="historyError" class="error" data-testid="history-error">
        加载失败：{{ historyError }}
      </p>
      <table v-else class="tbl">
        <thead><tr><th>#</th><th>汇总</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>#{{ h.id }}</td>
            <td>
              通过 {{ h.pass_count }} / 失败 {{ h.fail_count }} /
              异常 {{ h.error_count }} / 预演 {{ h.shadow_count }}
            </td>
            <td>{{ h.created_at.replace("T", " ").slice(0, 16) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.suite-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.suite-head h2 {
  margin: 0;
  border-bottom: none;
}
.suite-skills {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  font-size: 13px;
}
</style>
