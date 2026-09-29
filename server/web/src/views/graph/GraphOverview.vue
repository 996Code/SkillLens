<script setup lang="ts">
// S40 系统总览 v2：真正的图渲染——流水线内嵌 SVG 流程图 +
// 操作流程按系统分组卡片（含节点色条预览）。不是文字链接假装是图。
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
    const sys = (s as { system?: string }).system || "其他";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  const order = ["njmind", "Odoo", "Dolibarr", "ERPNext"];
  return [...groups.entries()].sort((a, b) => {
    const ai = order.indexOf(a[0]), bi = order.indexOf(b[0]);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
  });
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
      流水线与操作流程以图组织。点流水线进入执行；点流程查看流程图。
    </p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <!-- 流水线：内嵌 SVG 流程图 -->
      <div class="block" data-testid="overview-pipelines">
        <h2>流水线（{{ suites.length }}）</h2>
        <p v-if="!suites.length" class="muted">
          暂无流水线，去
          <RouterLink to="/graph/suites">套件管理</RouterLink> 创建
        </p>
        <div v-else class="pipe-grid">
          <div v-for="s in suites" :key="s.id" class="pipe-card"
               :data-testid="`pipe-${s.id}`">
            <div class="pipe-head">
              <span class="pipe-name">{{ s.name }}</span>
              <RouterLink to="/graph/suites" class="btn btn-sm">管理</RouterLink>
            </div>
            <div class="pipe-flow-svg">
              <svg viewBox="0 0 300 60" class="pipe-svg">
                <rect x="10" y="15" width="70" height="30" rx="6"
                      fill="var(--color-primary-soft)" stroke="var(--color-primary)" stroke-width="1.5"/>
                <text x="45" y="35" text-anchor="middle" font-size="10" fill="var(--color-primary)">
                  流程×{{ s.skills.length }}
                </text>
                <line x1="80" y1="30" x2="110" y2="30" stroke="var(--color-gray-4)" stroke-width="1.5"
                      marker-end="url(#arrow)"/>
                <rect x="115" y="15" width="70" height="30" rx="6"
                      fill="var(--color-warning-soft)" stroke="var(--color-warning)" stroke-width="1.5"/>
                <text x="150" y="35" text-anchor="middle" font-size="10" fill="var(--color-warning)">
                  批量测试
                </text>
                <line x1="185" y1="30" x2="215" y2="30" stroke="var(--color-gray-4)" stroke-width="1.5"
                      marker-end="url(#arrow)"/>
                <rect x="220" y="15" width="70" height="30" rx="6"
                      fill="var(--color-gray-2)" stroke="var(--color-gray-5)" stroke-width="1.5"/>
                <text x="255" y="35" text-anchor="middle" font-size="10" fill="var(--color-gray-7)">
                  汇总
                </text>
                <defs>
                  <marker id="arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
                    <path d="M0,0 L8,3 L0,6" fill="var(--color-gray-4)"/>
                  </marker>
                </defs>
              </svg>
            </div>
            <div class="pipe-meta">
              <span v-for="sk in s.skills.slice(0, 3)" :key="sk.id" class="chip">
                {{ sk.system }}
              </span>
              <span v-if="s.skills.length > 3" class="muted">+{{ s.skills.length - 3 }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 操作流程：按系统分组，卡片含节点色条预览 -->
      <div class="block" data-testid="overview-skills">
        <h2>操作流程（{{ skills.length }}）</h2>
        <div v-for="[sys, list] in bySystem" :key="sys" class="sys-group">
          <div class="sys-head">
            <span class="sys-dot" :data-sys="sys"></span>
            <span class="sys-name">{{ sys }}</span>
            <span class="muted">{{ list.length }} 个</span>
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
              <span class="flow-preview">
                <i class="fp-node page"></i><span class="fp-arrow">→</span><i class="fp-node action"></i><span class="fp-arrow">→</span><i class="fp-node assert"></i>
              </span>
              <span class="flow-meta muted">
                {{ s.status }} · {{ Math.round(s.confidence * 100) }}%
              </span>
            </RouterLink>
          </div>
        </div>
        <p v-if="skills.length === 0" class="muted">
          暂无操作流程，先录制一轮操作
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.pipe-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-3);
}
.pipe-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
}
.pipe-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}
.pipe-name {
  font-weight: 700;
  font-size: 14px;
}
.btn-sm {
  padding: 2px 10px;
  font-size: 11px;
}
.pipe-flow-svg {
  margin-bottom: var(--space-2);
}
.pipe-svg {
  width: 100%;
  height: auto;
  display: block;
}
.pipe-meta {
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
.sys-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.sys-dot[data-sys="njmind"] { background: #3b82f6; }
.sys-dot[data-sys="Odoo"] { background: #8b5cf6; }
.sys-dot[data-sys="Dolibarr"] { background: #f59e0b; }
.sys-dot[data-sys="ERPNext"] { background: #10b981; }
.sys-dot[data-sys="其他"] { background: #9ca3af; }
.sys-name {
  font-weight: 700;
  font-size: 14px;
  color: var(--color-gray-8);
}
.flow-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-2);
}
.flow-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.flow-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}
.flow-name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.flow-preview {
  display: flex;
  align-items: center;
  gap: 3px;
}
.fp-node {
  width: 18px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}
.fp-node.page { background: #3b82f6; }
.fp-node.action { background: #f59e0b; }
.fp-node.assert { background: #16a34a; }
.fp-arrow {
  font-size: 9px;
  color: var(--color-gray-4);
}
.flow-meta {
  font-size: 11px;
}
</style>
