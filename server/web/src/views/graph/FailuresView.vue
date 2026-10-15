<script setup lang="ts">
// 失败分析工作台（UI 批2）：AJ1 分类学 E1-E4 落列以来首次有聚合视图——
// 按类聚合卡 + 可展开最近 run 行（直通 run 详情）。口径与 pass_rate 同源。
import { onMounted, ref } from "vue";
import { getFailuresSummary } from "../../api";
import type { FailuresSummary } from "../../api";

const data = ref<FailuresSummary | null>(null);
const loading = ref(true);
const error = ref("");
const days = ref(30);
const open = ref<Record<string, boolean>>({});

const CLASS_DESC: Record<string, string> = {
  e1_env: "目标系统未就绪/登录态丢失（环境问题，不进通过率分母）",
  e2_infra: "SkillLens 基础设施故障（通道/预算/熔断，不进分母）",
  e3_drift: "页面/接口漂移——UI 变化或定位失效",
  e4_assert: "断言失败——业务行为偏离期望",
  unclassified: "未分类（老数据或分类通道缺席）",
};

const toneOf = (cls: string) =>
  cls === "e1_env" || cls === "e2_infra" ? "muted" :
  cls === "e3_drift" ? "warn" : cls === "e4_assert" ? "fail" : "";

import { computed } from "vue";

// 审查 D 批：占比可视化（1700/1768≈96% 不再需要心算）
function barWidth(count: number): string {
  if (!data.value?.total) return "0%";
  return `${Math.round((count / data.value.total) * 100)}%`;
}
const topClass = computed(() => {
  if (!data.value?.by_class) return null;
  let best: [string, number, string] | null = null;
  for (const [cls, agg] of Object.entries(data.value.by_class)) {
    if (!best || agg.count > best[1]) best = [cls, agg.count, agg.label];
  }
  return best;
});
const topRate = computed(() =>
  topClass.value ? barWidth(topClass.value[1]).replace("%", "") : null);
const topLabel = computed(() => topClass.value?.[2] ?? "");

function fmtAgo(ts: string): string {
  const m = Math.floor((Date.now() - new Date(ts).getTime()) / 60000);
  if (m < 60) return `${Math.max(m, 1)} 分钟前`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h} 小时前` : `${Math.floor(h / 24)} 天前`;
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    data.value = await getFailuresSummary(days.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section>
    <div class="fail-head">
      <h1>失败分析</h1>
      <select v-model.number="days" class="fail-days" data-testid="failures-days"
              @change="load()">
        <option :value="7">近 7 天</option>
        <option :value="30">近 30 天</option>
        <option :value="90">近 90 天</option>
      </select>
    </div>
    <p class="muted page-desc">按失败分类聚合（E1 环境/E2 基础设施不进通过率分母；E3 漂移/E4 断言是真失败信号）。</p>

    <div v-if="loading" class="loading-skeleton"><div class="skeleton skeleton-line" style="width: 40%"></div><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line" style="width: 70%"></div></div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="!data || !data.total" class="empty block" data-testid="failures-empty">
      所选窗口内没有失败运行。
    </div>

    <template v-else>
      <div class="page-toolbar">
        <span class="summary" data-testid="failures-total">
          共 <b>{{ data.total }}</b> 次失败/异常
          <template v-if="data.unclassified">
            · 未分类 {{ data.unclassified }}
          </template>
        </span>
        <span class="spacer"></span>
        <span class="summary" v-if="topRate !== null"
              :title="'占比最高的一类失败'">
          {{ topLabel }} 占 {{ topRate }}%
        </span>
      </div>
      <div v-for="[cls, agg] in Object.entries(data.by_class)" :key="cls"
           class="block fail-class-card" :data-testid="`failures-${cls}`">
        <div class="fail-class-head" role="button" tabindex="0"
             :aria-expanded="!!open[cls]"
             @click="open[cls] = !open[cls]"
             @keydown.enter.prevent="open[cls] = !open[cls]"
             @keydown.space.prevent="open[cls] = !open[cls]">
          <span class="badge" :class="toneOf(cls) ? `badge-${toneOf(cls) === 'muted' ? '' : cls}` : ''">
            {{ agg.label }}
          </span>
          <span class="fail-count">{{ agg.count }}</span>
          <span class="fail-bar" :title="`${agg.count} / ${data.total}`">
            <i :style="{ width: barWidth(agg.count) }"></i>
          </span>
          <span class="muted fail-pct">{{ barWidth(agg.count) }}</span>
          <span class="muted fail-desc">{{ CLASS_DESC[cls] ?? cls }}</span>
          <span class="fail-toggle">{{ open[cls] ? "收起 ▴" : "明细 ▾" }}</span>
        </div>
        <table v-if="open[cls]" class="tbl">
          <thead>
            <tr><th>Run</th><th>技能</th><th>系统</th><th>状态</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in agg.runs" :key="r.id">
              <td><RouterLink :to="`/graph/run/${r.id}`">#{{ r.id }}</RouterLink></td>
              <td><RouterLink :to="`/graph/skill/${r.skill_id}`">{{ r.skill_name }}</RouterLink></td>
              <td class="muted">{{ r.system }}</td>
              <td><span class="badge" :class="`badge-${r.status}`">{{ r.status }}</span></td>
              <td class="muted">{{ fmtAgo(r.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.fail-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.fail-days {
  padding: 4px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}
.fail-class-card {
  margin-bottom: var(--space-3);
}
.fail-class-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  cursor: pointer;
  user-select: none;
}
.fail-class-head:focus-visible {
  outline: 2px solid var(--color-primary-border);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}
.fail-class-head:hover .fail-toggle {
  color: var(--color-primary);
}
.fail-count {
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  min-width: 52px;
  text-align: right;
}
.fail-bar {
  width: 120px;
  height: 6px;
  border-radius: 3px;
  background: var(--color-gray-2);
  overflow: hidden;
  flex: none;
}
.fail-bar i {
  display: block;
  height: 100%;
  border-radius: 3px;
  background: var(--color-primary);
}
.fail-pct {
  font-size: 12px;
  width: 40px;
  font-variant-numeric: tabular-nums;
  flex: none;
}
.fail-desc {
  flex: 1;
  font-size: 12px;
}
.fail-toggle {
  font-size: 12px;
  color: var(--color-gray-6);
}
</style>
