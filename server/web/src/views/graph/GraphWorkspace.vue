<script setup lang="ts">
// S39b 图工作台壳（唯一导航壳）：左树=全系统导航 + 登出；
// 中=RouterView（所有页面都在壳内渲染）。
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getSkills, listSuites, logout } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";

const route = useRoute();
const router = useRouter();
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

async function doLogout(): Promise<void> {
  await logout();
  router.push("/login");
}
</script>

<template>
  <div class="gw-shell" data-testid="graph-workspace">
    <!-- 左：全系统导航树 -->
    <aside class="gw-tree">
      <div class="gw-brand">SkillLens</div>
      <RouterLink to="/graph" class="gw-tree-root" data-testid="gw-overview-link">
        ◈ 系统总览
      </RouterLink>

      <div class="gw-tree-group">流水线（{{ suites.length }}）</div>
      <RouterLink to="/graph/suites" class="gw-tree-leaf">▤ 套件管理</RouterLink>
      <RouterLink
        v-for="s in suites.slice(0, 5)"
        :key="s.id"
        to="/graph/suites"
        class="gw-tree-leaf"
      >
        └ {{ s.name }}
      </RouterLink>

      <div class="gw-tree-group">操作流程（{{ skills.length }}）</div>
      <div class="gw-tree-scroll">
        <RouterLink
          v-for="s in skills"
          :key="s.id"
          :to="`/graph/skill/${s.id}`"
          class="gw-tree-leaf"
          :class="{ active: currentSkillId === String(s.id) }"
        >
          <span class="gw-sys">{{ (s as { system?: string }).system || "" }}</span>
          {{ s.name }}
        </RouterLink>
      </div>

      <div class="gw-tree-group">测试活动</div>
      <RouterLink to="/graph/timeline" class="gw-tree-leaf">⌇ 时间线</RouterLink>

      <div class="gw-tree-group">工具</div>
      <RouterLink to="/graph/canvas" class="gw-tree-leaf">✎ 编排画布</RouterLink>
      <RouterLink to="/graph/audit" class="gw-tree-leaf">⬡ 审计</RouterLink>
      <RouterLink to="/graph/reports/1" class="gw-tree-leaf">⌕ 报告</RouterLink>
      <RouterLink to="/graph/reviews-portal" class="gw-tree-leaf">✓ 评审</RouterLink>

      <div class="gw-tree-foot">
        <button class="logout-btn" data-testid="logout-btn" @click="doLogout">
          登出
        </button>
        <div class="tagline">变更智能工作台</div>
      </div>
    </aside>

    <!-- 中：当前页面（所有路由都在壳内） -->
    <main class="gw-canvas">
      <RouterView @graph-changed="load" />
    </main>
  </div>
</template>

<style scoped>
.gw-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.gw-tree {
  width: 230px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-gray-1);
  overflow-y: auto;
  padding: var(--space-3) var(--space-2);
  display: flex;
  flex-direction: column;
}
.gw-brand {
  font-weight: 700;
  font-size: 16px;
  color: var(--color-gray-8);
  padding: var(--space-2) var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--color-gray-3);
  margin-bottom: var(--space-2);
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
  max-height: 35vh;
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
.gw-tree-foot {
  margin-top: auto;
  padding: var(--space-3) var(--space-2);
  border-top: 1px solid var(--color-gray-3);
}
.logout-btn {
  width: 100%;
  padding: 6px 0;
  background: transparent;
  color: var(--color-gray-5);
  border: 1px solid var(--color-gray-4);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.logout-btn:hover {
  color: var(--color-danger);
  border-color: var(--color-danger);
}
.tagline {
  font-size: 11px;
  color: var(--color-gray-5);
  text-align: center;
  margin-top: var(--space-1);
}
.gw-canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6);
}
</style>
