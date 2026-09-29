<script setup lang="ts">
// S39 图工作台壳：流程图基座的导航骨架——
//   左：图导航树（系统总览→流水线→流程，当前层高亮）
//   中：当前层级的图（RouterView：总览/流程图/执行图）
// 旧页面（报告/审计/编排等）保留深链，从树底部可达。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getSkills, listSuites } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";

const route = useRoute();
const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const loading = ref(true);

const currentSkillId = computed(() =>
  route.name === "graph-skill" ? String(route.params.skillId) : "");

async function load(): Promise<void> {
  loading.value = true;
  try {
    [suites.value, skills.value] = await Promise.all([listSuites(), getSkills()]);
  } finally {
    loading.value = false;
  }
}
onMounted(() => void load());
</script>

<template>
  <div class="gw-shell" data-testid="graph-workspace">
    <!-- 左：图导航树 -->
    <aside class="gw-tree">
      <div class="gw-tree-title">图导航</div>
      <RouterLink to="/graph" class="gw-tree-root" data-testid="gw-overview-link">
        ◈ 系统总览
      </RouterLink>
      <div v-if="suites.length" class="gw-tree-group">流水线</div>
      <RouterLink
        v-for="s in suites"
        :key="s.id"
        to="/suites"
        class="gw-tree-leaf"
      >
        ▤ {{ s.name }}
      </RouterLink>
      <div class="gw-tree-group">操作流程（{{ skills.length }}）</div>
      <div class="gw-tree-scroll">
        <RouterLink
          v-for="s in skills"
          :key="s.id"
          :to="`/graph/skill/${s.id}`"
          class="gw-tree-leaf"
          :class="{ active: currentSkillId === String(s.id) }"
          :data-testid="`gw-skill-${s.id}`"
        >
          <span class="gw-sys">{{ (s as { system?: string }).system || "" }}</span>
          {{ s.name }}
        </RouterLink>
      </div>
      <div class="gw-tree-group">其他</div>
      <RouterLink to="/dashboard" class="gw-tree-leaf">▤ 仪表盘</RouterLink>
      <RouterLink to="/reports/1" class="gw-tree-leaf">⌕ 报告</RouterLink>
      <RouterLink to="/audit" class="gw-tree-leaf">⬡ 审计</RouterLink>
      <RouterLink to="/canvas" class="gw-tree-leaf">✎ 编排</RouterLink>
    </aside>

    <!-- 中：当前层级的图 -->
    <main class="gw-canvas">
      <RouterView @graph-changed="load" />
    </main>
  </div>
</template>

<style scoped>
.gw-shell {
  display: flex;
  height: calc(100vh - 0px);
  overflow: hidden;
  margin: calc(-1 * var(--space-6)) calc(-1 * var(--space-8));
}
.gw-tree {
  width: 230px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-gray-1);
  overflow-y: auto;
  padding: var(--space-3) var(--space-2);
}
.gw-tree-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-gray-5);
  padding: 0 var(--space-2) var(--space-2);
  letter-spacing: 0.05em;
}
.gw-tree-root {
  display: block;
  padding: 7px var(--space-2);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  color: var(--color-gray-8);
  text-decoration: none;
}
.gw-tree-root.router-link-active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}
.gw-tree-group {
  font-size: 11px;
  color: var(--color-gray-5);
  padding: var(--space-3) var(--space-2) var(--space-1);
  font-weight: 600;
}
.gw-tree-scroll {
  max-height: 40vh;
  overflow-y: auto;
}
.gw-tree-leaf {
  display: block;
  padding: 5px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-gray-7);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gw-tree-leaf:hover {
  background: var(--color-gray-2);
}
.gw-tree-leaf.active,
.gw-tree-leaf.router-link-active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}
.gw-sys {
  font-size: 10px;
  color: var(--color-gray-5);
  margin-right: 4px;
}
.gw-canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6);
}
</style>
