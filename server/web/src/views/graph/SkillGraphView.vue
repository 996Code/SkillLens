<script setup lang="ts">
// S39 操作流程图（图工作台内）：骨架+断言 → 节点图；
// 底部该流程的执行历史（点开=执行图）。下钻链：总览→流程图→执行图。
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getSkillCard, getSkillFlow } from "../../api";
import type { FlowGraphDTO, SkillCard } from "../../api";
import FlowGraph from "../../components/FlowGraph.vue";

const route = useRoute();
const card = ref<SkillCard | null>(null);
const flow = ref<FlowGraphDTO | null>(null);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    [card.value, flow.value] = await Promise.all([
      getSkillCard(String(route.params.skillId)),
      getSkillFlow(String(route.params.skillId)),
    ]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card && flow">
      <h1>{{ card.name }}</h1>
      <p class="muted page-desc">
        {{ card.description }} · 置信度 {{ Math.round(card.confidence * 100) }}% ·
        证据 {{ card.evidence_count }}
      </p>

      <!-- 流程图（骨架+断言节点） -->
      <div class="block" data-testid="skill-flow-block">
        <h2>流程图</h2>
        <p class="muted hint">
          页面 → 操作 → 断言 的节点链；点击节点查看签名与断言详情。
        </p>
        <FlowGraph :nodes="flow.nodes" :edges="flow.edges" />
      </div>

      <!-- 执行历史（下钻到执行图） -->
      <div v-if="card.last_run" class="block" data-testid="skill-run-history">
        <h2>最近执行</h2>
        <RouterLink :to="`/graph/run/${card.last_run.id}`" class="run-link">
          <span class="dot" :class="`dot-${card.last_run.status}`"></span>
          {{ card.last_run.status }} · {{ card.last_run.mode }} ·
          {{ card.last_run.ts.replace("T", " ").slice(0, 16) }}
          <span class="muted">（点开看执行图）</span>
        </RouterLink>
      </div>
    </template>
  </section>
</template>

<style scoped>
.hint {
  margin-top: 0;
  font-size: 12px;
}
.run-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 14px;
  text-decoration: none;
}
</style>
