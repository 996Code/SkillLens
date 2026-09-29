<script setup lang="ts">
// S39 系统总览（图工作台首页）：流水线图卡片 + 按系统分组的操作流程图入口。
// 打开系统=看到图，点卡片=下钻。
import { computed, onMounted, ref } from "vue";
import { getSkills, listSuites } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";

const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const loading = ref(true);
const error = ref("");

const bySystem = computed(() => {
  const groups = new Map<string, SkillListItem[]>();
  for (const s of skills.value) {
    const sys = (s as { system?: string }).system || "未知系统";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
});

onMounted(async () => {
  try {
    [suites.value, skills.value] = await Promise.all([listSuites(), getSkills()]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>系统总览</h1>
    <p class="muted page-desc">
      流水线与操作流程以图组织：点流水线进入编排执行；点流程查看流程图与执行历史。
    </p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <!-- 流水线图卡片 -->
      <div class="block" data-testid="overview-pipelines">
        <h2>流水线（{{ suites.length }}）</h2>
        <p v-if="!suites.length" class="muted">
          暂无流水线，去
          <RouterLink to="/suites">套件页</RouterLink> 创建
        </p>
        <div v-else class="pipe-grid">
          <RouterLink
            v-for="s in suites"
            :key="s.id"
            to="/suites"
            class="pipe-card"
            :data-testid="`pipe-${s.id}`"
          >
            <div class="pipe-name">{{ s.name }}</div>
            <div class="pipe-flow">
              <span class="pf-node">流程×{{ s.skills.length }}</span>
              <span class="pf-arrow">→</span>
              <span class="pf-node">批量测试</span>
              <span class="pf-arrow">→</span>
              <span class="pf-node">汇总</span>
            </div>
            <div class="pipe-systems">
              <span v-for="sk in s.skills.slice(0, 4)" :key="sk.id" class="chip">
                {{ sk.system }}
              </span>
            </div>
          </RouterLink>
        </div>
      </div>

      <!-- 操作流程（按系统分组，图入口） -->
      <div class="block" data-testid="overview-skills">
        <h2>操作流程（{{ skills.length }}）</h2>
        <div v-for="[sys, list] in bySystem" :key="sys" class="sys-group">
          <div class="sys-head">
            <span class="sys-name">{{ sys }}</span>
            <span class="muted">{{ list.length }} 个流程</span>
          </div>
          <div class="flow-grid">
            <RouterLink
              v-for="s in list"
              :key="s.id"
              :to="`/graph/skill/${s.id}`"
              class="flow-card"
              :data-testid="`flow-${s.id}`"
            >
              <span class="flow-name">{{ s.name }}</span>
              <span class="flow-steps">
                页面 → 操作 → 断言
              </span>
            </RouterLink>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.pipe-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-3);
}
.pipe-card {
  display: block;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.pipe-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}
.pipe-name {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: var(--space-2);
}
.pipe-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--space-2);
}
.pf-node {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
}
.pf-arrow {
  color: var(--color-gray-4);
  font-size: 12px;
}
.pipe-systems {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.sys-group {
  margin-bottom: var(--space-4);
}
.sys-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.sys-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-primary);
}
.flow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-2);
}
.flow-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease;
}
.flow-card:hover {
  border-color: var(--color-primary);
}
.flow-name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flow-steps {
  font-size: 11px;
  color: var(--color-gray-5);
  font-family: var(--font-mono);
}
</style>
