<script setup lang="ts">
// AQ1 测试场景列表（信息架构重设计）：链=用户工作层（业界 Case/Suite
// 共识）——按系统分组卡片，业务名+步骤数+最近运行徽章。技术层（249
// 技能）收进步骤库，此页不出现技术名。
import { computed, onMounted, ref } from "vue";
import { listScenarios, listSkillRuns } from "../../api";
import type { ScenarioListItem, SkillRunRow } from "../../api";
import { groupBySystem, systemColor } from "../../system-group";

const scenarios = ref<ScenarioListItem[]>([]);
const loading = ref(true);
const error = ref("");

// 每条链的最近一次运行（链执行=逐 skill 产生 run——取链首 skill 最新
// run 作为链级状态近似；准确链级聚合留后续批）
const lastRunByScenario = ref<Record<number, SkillRunRow | null>>({});

const grouped = computed(() => groupBySystem(scenarios.value));

async function load(): Promise<void> {
  loading.value = true;
  try {
    scenarios.value = await listScenarios();
    // 链级最近 run（首 skill 近似）
    await Promise.all(scenarios.value.slice(0, 20).map(async (c) => {
      const first = c.steps.find((s) => s.skill_id);
      if (!first) return;
      try {
        const runs = await listSkillRuns(first.skill_id!);
        lastRunByScenario.value[c.id] = runs[0] ?? null;
      } catch {
        lastRunByScenario.value[c.id] = null;
      }
    }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function fmtAgo(ts: string): string {
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 60) return `${Math.max(m, 1)} 分钟前`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} 小时前` : `${Math.floor(h / 24)} 天前`;
}

onMounted(load);
</script>

<template>
  <section>
    <h1>测试场景</h1>
    <p class="muted page-desc">按业务流程组织的自动化测试——点场景查看步骤、运行或编辑。</p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="!scenarios.length" class="empty block" data-testid="scenarios-empty">
      暂无测试场景。录制操作后，在浏览器插件的空间面板里组合技能即可创建场景。
    </div>

    <template v-else>
      <div v-for="[sys, list] in grouped" :key="sys" class="sys-section">
        <div class="sys-head">
          <span class="sys-dot" :style="{ background: systemColor(sys) }"></span>
          <span class="sys-name">{{ sys }}</span>
          <span class="muted">{{ list.length }} 个场景</span>
        </div>
        <div class="scenario-grid">
          <RouterLink v-for="c in list" :key="c.id"
                      :to="`/graph/scenario/${c.id}`"
                      class="scenario-card"
                      :data-testid="`scenario-${c.id}`">
            <div class="scenario-name">{{ c.name }}</div>
            <div class="scenario-meta">
              <span class="muted">{{ c.steps.length }} 步</span>
              <span v-if="lastRunByScenario[c.id]"
                    class="badge"
                    :class="`badge-${lastRunByScenario[c.id]!.status}`">
                {{ lastRunByScenario[c.id]!.status }}
                <span class="muted scenario-ago">
                  · {{ fmtAgo(lastRunByScenario[c.id]!.created_at) }}
                </span>
              </span>
              <span v-else class="badge">未运行</span>
            </div>
          </RouterLink>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.sys-section {
  margin-bottom: var(--space-6);
}
.sys-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.sys-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.sys-name {
  font-weight: 700;
  font-size: 14px;
}
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}
.scenario-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-4) var(--space-5);
  text-decoration: none;
  color: inherit;
  transition: box-shadow var(--dur-mid) var(--ease-out),
    transform var(--dur-mid) var(--ease-out),
    border-color var(--dur-mid) var(--ease-out);
}
.scenario-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
  text-decoration: none;
}
.scenario-name {
  font-size: 14px;
  font-weight: 650;
  line-height: 1.4;
}
.scenario-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 12px;
}
.scenario-ago {
  font-weight: 400;
  font-size: 11px;
}
</style>
