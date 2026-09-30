<script setup lang="ts">
// S43-2 学习图（审计 trace 图化）：归纳管道五层
// session → window → semantic → align → skill，图基座第二步。
import { onMounted, ref } from "vue";
import { getLearningGraph } from "../../api";
import type { FlowGraphDTO } from "../../api";
import FlowGraph from "../../components/FlowGraph.vue";

const graph = ref<FlowGraphDTO | null>(null);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    graph.value = await getLearningGraph();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>学习图</h1>
    <p class="muted page-desc">
      归纳管道 trace 图化：会话 → 窗口 → 语义动作 → 对齐 → 技能（最近 30 个会话）。
    </p>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <template v-else-if="graph">
      <p v-if="graph.nodes.length === 0" class="muted" data-testid="learning-empty">
        暂无学习数据——录制会话并归纳后在此呈现
      </p>
      <FlowGraph v-else :nodes="graph.nodes" :edges="graph.edges" data-testid="learning-graph" />
    </template>
  </section>
</template>
