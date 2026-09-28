<script setup lang="ts">
// S34 块 1：回放 run 详情页（竞品差距补齐——run 级下钻：步骤+截图墙+
// 断言明细+归因+前后快照对比，一页全览）。
// 入口：时间线 replay 项"下钻查看"；数据 GET /replay-runs/{id}。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getReplayRun } from "../api";
import type { ReplayRunDetail } from "../api";
import ShotGallery from "../components/ShotGallery.vue";
import type { ShotItem } from "../components/ShotGallery.vue";
import {
  assertExpect,
  assertObserved,
  shotCaption,
  snapshotDiffRows,
  stepScreenshotFiles,
} from "../run-format";

const route = useRoute();
const run = ref<ReplayRunDetail | null>(null);
const loading = ref(true);
const notFound = ref(false);
const error = ref("");

const snapshotDiff = computed(() => snapshotDiffRows(run.value?.plan ?? null));

const shotItems = computed<ShotItem[]>(() => {
  const meta = stepScreenshotFiles(run.value?.plan ?? null);
  if (!meta) return [];
  return meta.files.map((file) => ({
    file,
    caption: shotCaption(file, run.value?.executed ?? null),
  }));
});

function fmtTime(ts: string | null | undefined): string {
  return ts ? ts.replace("T", " ").replace(/\.\d+.*$/, "") : "—";
}

onMounted(async () => {
  try {
    run.value = await getReplayRun(String(route.params.runId));
  } catch (e) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      notFound.value = true;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <div v-else-if="notFound" class="empty">
      <span class="empty-icon">∅</span>
      <h1 class="empty-title">404</h1>
      <p class="empty-sub">回放 run 不存在（<RouterLink to="/timeline">返回时间线</RouterLink>）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="run">
      <header>
        <h1>回放 run #{{ run.id }}</h1>
        <p class="run-line">
          <RouterLink :to="`/skills/${run.skill_id}`">Skill #{{ run.skill_id }}</RouterLink>
          <span class="run-status" :class="`st-${run.status}`">{{ run.status }}</span>
          <span class="badge badge-kind">{{ run.mode }}</span>
          <span v-if="run.flaky" class="badge badge-changes_requested">flaky</span>
          <span class="muted">
            {{ run.duration_ms == null ? "—" : `${run.duration_ms}ms` }} ·
            {{ fmtTime(run.created_at) }}
          </span>
        </p>
        <p class="muted status-legend">
          pass=全断言通过 fail=有断言失败 shadow=只规划未执行 error=执行异常
        </p>
      </header>

      <!-- 执行步骤（含每步截图） -->
      <div class="block">
        <h2>执行步骤（{{ run.executed?.length ?? 0 }}）</h2>
        <p v-if="!run.executed?.length" class="muted">
          {{ run.mode === "shadow" ? "shadow run 未执行，无步骤。" : "无步骤记录。" }}
        </p>
        <table v-else class="tbl">
          <thead>
            <tr><th>#</th><th>kind</th><th>目标</th><th>定位策略</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="(s, i) in run.executed" :key="i">
              <td>{{ i + 1 }}</td>
              <td><span class="chip chip-kind">{{ s.kind }}</span></td>
              <td class="mono">{{ s.label ?? s.name ?? "—" }}</td>
              <td class="mono">{{ s.strategy ?? "—" }}</td>
              <td>
                <span v-if="s.ok" class="ok">ok</span>
                <span v-else class="ng">{{ s.error ?? "failed" }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 步骤截图墙（点击放大） -->
      <div class="block" v-if="shotItems.length">
        <h2>步骤画面（{{ shotItems.length }}）</h2>
        <p class="muted hint">点击缩略图放大查看。</p>
        <ShotGallery :run-id="run.id" :items="shotItems" />
      </div>

      <!-- 断言明细 -->
      <div v-if="run.assertion_results?.length" class="block">
        <h2>断言明细（{{ run.assertion_results.length }}）</h2>
        <table class="tbl">
          <thead>
            <tr><th>kind</th><th>期望</th><th>观察</th><th>结果</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in run.assertion_results" :key="i">
              <td><span class="chip chip-kind">{{ r.kind }}</span></td>
              <td class="mono">{{ assertExpect(r) }}</td>
              <td class="mono">{{ assertObserved(r) }}</td>
              <td>
                <span v-if="r.skipped" class="skipped">skipped（{{ r.skipped }}）</span>
                <span v-else-if="r.passed" class="ok">passed</span>
                <span v-else class="ng">FAILED</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 失败归因 -->
      <div v-if="run.attribution" class="block">
        <h2>失败归因</h2>
        <pre class="code attribution">{{ run.attribution }}</pre>
      </div>

      <!-- 前后快照对比 -->
      <div v-if="snapshotDiff.length" class="block">
        <h2>回放前后快照对比（forms）</h2>
        <p class="muted hint">只显示有差异的字段（前 10 行）。</p>
        <table class="tbl">
          <thead><tr><th>字段</th><th>before → after</th></tr></thead>
          <tbody>
            <tr v-for="(d, i) in snapshotDiff" :key="i">
              <td>{{ d.label }}</td>
              <td class="mono">{{ d.from }} → {{ d.to }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
header h1 {
  margin: 0 0 var(--space-1);
  font-size: 20px;
}
.run-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
  font-size: 15px;
}
.run-status {
  font-size: 22px;
  font-weight: 700;
  padding: 0 10px;
  border-radius: var(--radius-md);
}
.st-pass { color: var(--color-success); }
.st-fail { color: var(--color-danger); }
.st-shadow { color: var(--color-gray-5); }
.st-error { color: var(--color-warning); }
.status-legend { font-size: 12px; }
.hint { margin-top: 0; font-size: 12px; }
.ok { color: var(--color-success); }
.ng { color: var(--color-danger); font-weight: 700; }
.skipped { color: var(--color-gray-5); }
</style>
