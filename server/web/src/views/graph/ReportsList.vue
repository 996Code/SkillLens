<script setup lang="ts">
// 报告列表（UI 优化批1）：此前无列表入口——侧栏写死 id=1 即 404 死胡同
// （当前库 0 份报告）。列表行轻量（计数），点行进四分类详情。
import { onMounted, ref } from "vue";
import { listReports } from "../../api";
import type { ReportListItem } from "../../api";

const rows = ref<ReportListItem[]>([]);
const loading = ref(true);
const error = ref("");

function fmtAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

onMounted(async () => {
  try {
    rows.value = await listReports();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>四分类报告</h1>
    <p class="muted page-desc">期望-观测对照的变更智能报告。</p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="!rows.length" class="empty block" data-testid="reports-empty">
      暂无报告。回放触发「对照观测」并生成差异报告后，会出现在这里。
    </div>
    <table v-else class="tbl" data-testid="reports-list">
      <thead>
        <tr>
          <th>报告</th><th>期望变更</th><th>观测变更</th>
          <th>期望</th><th>缺失</th><th>意外</th><th>漂移</th><th>时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>
            <RouterLink :to="`/graph/reports/${r.id}`">#{{ r.id }}</RouterLink>
          </td>
          <td class="muted">{{ r.expected_delta_id }}</td>
          <td class="muted">{{ r.observed_delta_id }}</td>
          <td>{{ r.expected_count }}</td>
          <td :class="{ 'tone-fail': r.missing_count > 0 }">{{ r.missing_count }}</td>
          <td :class="{ 'tone-warn': r.unexpected_count > 0 }">{{ r.unexpected_count }}</td>
          <td>{{ r.drift_count }}</td>
          <td class="muted">{{ fmtAgo(r.created_at) }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.tone-fail { color: var(--color-danger, #dc2626); font-weight: 600; }
.tone-warn { color: var(--color-warning, #d97706); font-weight: 600; }
</style>
