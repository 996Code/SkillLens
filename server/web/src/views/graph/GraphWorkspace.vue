<script setup lang="ts">
// S40 图工作台壳 v2：左树=分组折叠+搜索+系统徽标；中=RouterView。
// 修复 S39 的"文字墙"问题：62 个流程不再平铺，按系统分组可折叠，
// 顶部搜索框实时过滤。
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getSkills, listSuites, logout } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";

const route = useRoute();
const router = useRouter();
const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const loading = ref(true);
const search = ref("");
const collapsed = ref<Set<string>>(new Set());

const currentSkillId = computed(() =>
  route.name === "graph-skill" ? String(route.params.skillId) : "");

// 按系统分组 + 搜索过滤
const grouped = computed(() => {
  const q = search.value.trim().toLowerCase();
  const groups = new Map<string, SkillListItem[]>();
  for (const s of skills.value) {
    if (q && !s.name.toLowerCase().includes(q)) continue;
    const sys = (s as { system?: string }).system || "其他";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  return [...groups.entries()].sort((a, b) => {
    // 主要系统排前面，"其他"排最后
    const order = ["njmind", "Odoo", "Dolibarr", "ERPNext"];
    const ai = order.indexOf(a[0]), bi = order.indexOf(b[0]);
    const av = ai === -1 ? 99 : ai, bv = bi === -1 ? 99 : bi;
    if (av !== bv) return av - bv;
    return a[0].localeCompare(b[0]);
  });
});

function toggleGroup(sys: string): void {
  if (collapsed.value.has(sys)) collapsed.value.delete(sys);
  else collapsed.value.add(sys);
}

function isCollapsed(sys: string): boolean {
  return collapsed.value.has(sys);
}

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
    <!-- 左：导航树（分组折叠+搜索） -->
    <aside class="gw-tree">
      <div class="gw-brand">SkillLens</div>

      <!-- 搜索框 -->
      <div class="gw-search">
        <input
          v-model="search"
          type="text"
          placeholder="搜索流程…"
          aria-label="搜索流程"
          data-testid="tree-search"
        />
      </div>

      <RouterLink to="/graph" class="gw-tree-root" data-testid="gw-overview-link">
        ◈ 系统总览
      </RouterLink>

      <!-- 流水线 -->
      <div class="gw-tree-group">流水线（{{ suites.length }}）</div>
      <RouterLink to="/graph/suites" class="gw-tree-leaf">▤ 套件管理</RouterLink>

      <!-- 操作流程：按系统分组可折叠 -->
      <div class="gw-tree-group">
        操作流程（{{ skills.length }}）
      </div>
      <div class="gw-tree-scroll">
        <div v-for="[sys, list] in grouped" :key="sys" class="gw-group">
          <button class="gw-group-head" @click="toggleGroup(sys)">
            <span class="gw-toggle">{{ isCollapsed(sys) ? "▸" : "▾" }}</span>
            <span class="gw-group-name">{{ sys }}</span>
            <span class="gw-group-count">{{ list.length }}</span>
          </button>
          <div v-if="!isCollapsed(sys)" class="gw-group-body">
            <RouterLink
              v-for="s in list"
              :key="s.id"
              :to="`/graph/skill/${s.id}`"
              class="gw-tree-leaf"
              :class="{ active: currentSkillId === String(s.id) }"
              :data-testid="`gw-skill-${s.id}`"
            >
              {{ s.name }}
            </RouterLink>
          </div>
        </div>
        <p v-if="grouped.length === 0 && !loading" class="gw-empty">无匹配流程</p>
      </div>

      <!-- 测试活动 -->
      <div class="gw-tree-group">测试活动</div>
      <RouterLink to="/graph/timeline" class="gw-tree-leaf">⌇ 时间线</RouterLink>

      <!-- 工具 -->
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

    <!-- 中：当前页面 -->
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
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--color-border);
  background: var(--color-gray-1);
  overflow-y: auto;
  padding: var(--space-2) var(--space-2);
  display: flex;
  flex-direction: column;
}
.gw-brand {
  font-weight: 700;
  font-size: 16px;
  color: var(--color-gray-8);
  padding: var(--space-2) var(--space-2) var(--space-2);
  border-bottom: 1px solid var(--color-gray-3);
  margin-bottom: var(--space-1);
}
.gw-search {
  padding: var(--space-1) var(--space-1) var(--space-2);
}
.gw-search input {
  width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
  font-size: 13px;
  background: var(--color-surface);
}
.gw-search input:focus {
  outline: 2px solid var(--color-primary-border);
  border-color: var(--color-primary);
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
  padding: var(--space-2) var(--space-2) var(--space-1);
  font-weight: 600;
}
.gw-tree-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.gw-group {
  margin-bottom: 2px;
}
.gw-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px var(--space-2);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-gray-7);
  cursor: pointer;
}
.gw-group-head:hover {
  background: var(--color-gray-2);
}
.gw-toggle {
  width: 14px;
  font-size: 10px;
  color: var(--color-gray-5);
}
.gw-group-name {
  flex: 1;
  text-align: left;
}
.gw-group-count {
  font-size: 10px;
  color: var(--color-gray-5);
  background: var(--color-gray-2);
  border-radius: 999px;
  padding: 1px 6px;
}
.gw-group-body {
  padding-left: 14px;
}
.gw-tree-leaf {
  display: block;
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 12px;
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
.gw-empty {
  font-size: 12px;
  color: var(--color-gray-5);
  padding: var(--space-2);
  text-align: center;
}
.gw-tree-foot {
  margin-top: auto;
  padding: var(--space-2);
  border-top: 1px solid var(--color-gray-3);
}
.logout-btn {
  width: 100%;
  padding: 5px 0;
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
  font-size: 10px;
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
