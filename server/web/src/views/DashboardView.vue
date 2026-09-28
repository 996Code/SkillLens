<script setup lang="ts">
// S28 块 Y：仪表盘首页——对标 Katalon TrueTest 首屏信息密度。
// 四区：统计卡排 / 回放趋势（SVG 面积图）/ 四分类分布（SVG 环形图）/ 最近活动流。
import { computed, onMounted, ref } from "vue";
import { getDashboard } from "../api";
import type { DashboardData } from "../api";

const data = ref<DashboardData | null>(null);
const loading = ref(true);
const error = ref("");

const passRate = computed(() => {
  const r = data.value?.replays;
  if (!r || r.total === 0) return 0;
  const executed = r.pass + r.fail + r.error;
  return executed === 0 ? 0 : Math.round((r.pass / executed) * 100);
});

/** 趋势面积图路径（14 天，双系列：total 底 + pass 填充）*/
const trendPath = computed(() => {
  const t = data.value?.trend ?? [];
  if (t.length < 2) return { area: "", line: "", max: 0 };
  const W = 560, H = 120, PAD = 4;
  const max = Math.max(...t.map((d) => d.total), 1);
  const x = (i: number) => PAD + (i * (W - PAD * 2)) / (t.length - 1);
  const y = (v: number) => H - PAD - (v / max) * (H - PAD * 2);
  const pts = t.map((d, i) => `${x(i)},${y(d.total)}`);
  const passPts = t.map((d, i) => `${x(i)},${y(d.pass)}`);
  return {
    area: `M${x(0)},${H - PAD} L${pts.join(" L")} L${x(t.length - 1)},${H - PAD} Z`,
    line: `M${pts.join(" L")}`,
    passLine: `M${passPts.join(" L")}`,
    max,
    W, H,
  };
});

/** 四分类环形图（最近报告）*/
const donut = computed(() => {
  const last = data.value?.reports.last;
  if (!last) return null;
  const items = [
    { label: "expected", value: last.expected, color: "#4f46e5" },
    { label: "missing", value: last.missing, color: "#dc2626" },
    { label: "unexpected", value: last.unexpected, color: "#d97706" },
    { label: "drift", value: last.drift, color: "#6b7280" },
  ];
  const total = items.reduce((s, i) => s + i.value, 0);
  if (total === 0) return { items, total: 0, segs: [] as unknown[] };
  const R = 52, C = 2 * Math.PI * R;
  let offset = 0;
  const segs = items.filter((i) => i.value > 0).map((i) => {
    const frac = i.value / total;
    const seg = {
      color: i.color, label: i.label, value: i.value,
      dash: `${frac * C} ${C - frac * C}`, offset: -offset * C,
    };
    offset += frac;
    return seg;
  });
  return { items, total, segs, R, C };
});

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "").slice(5, 16);
}

onMounted(async () => {
  try {
    data.value = await getDashboard();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="dash" data-testid="dashboard">
    <h1>仪表盘</h1>
    <p class="page-desc">变更智能全景——技能健康、回放趋势、四分类分布、最近活动。</p>

    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 5" :key="i" class="skeleton-card"></div>
    </div>
    <p v-else-if="error" class="error">{{ error }}</p>
    <template v-else-if="data">

      <!-- ① 统计卡排（大数字，对标 Katalon TrueTest）-->
      <div class="stat-row" data-testid="stat-row">
        <div class="stat-card">
          <span class="stat-num">{{ data.skills.total }}</span>
          <span class="stat-label">技能总数</span>
          <span class="stat-sub">{{ data.skills.learned }} learned · {{ data.skills.candidate }} candidate</span>
        </div>
        <div class="stat-card">
          <span class="stat-num">{{ data.skills.generic_learned }}</span>
          <span class="stat-label">通用能力</span>
          <span class="stat-sub">跨系统 learned</span>
        </div>
        <div class="stat-card">
          <span class="stat-num" :class="passRate >= 80 ? 'ok' : passRate >= 50 ? 'warn' : 'bad'">{{ passRate }}%</span>
          <span class="stat-label">回放通过率</span>
          <span class="stat-sub">{{ data.replays.pass }}/{{ data.replays.pass + data.replays.fail + data.replays.error }} execute</span>
        </div>
        <div class="stat-card">
          <span class="stat-num" :class="data.replays.flaky > 0 ? 'warn' : ''">{{ data.replays.flaky }}</span>
          <span class="stat-label">flaky 回放</span>
          <span class="stat-sub">不稳定信号</span>
        </div>
        <div class="stat-card">
          <span class="stat-num">{{ data.reports.total }}</span>
          <span class="stat-label">四分类报告</span>
          <span class="stat-sub">{{ data.reviews_pending }} 待评审</span>
        </div>
      </div>

      <div class="grid-2">
        <!-- ② 回放趋势（14 天面积图）-->
        <div class="block chart-block" data-testid="trend-block">
          <h2>回放趋势（14 天）</h2>
          <svg v-if="trendPath.max > 0" :viewBox="`0 0 ${trendPath.W} ${trendPath.H}`" class="trend-svg">
            <path :d="trendPath.area" fill="var(--color-primary)" opacity="0.12" />
            <path :d="trendPath.line" fill="none" stroke="var(--color-primary)" stroke-width="2" />
            <path :d="trendPath.passLine" fill="none" stroke="var(--color-success)" stroke-width="2" stroke-dasharray="4 3" />
          </svg>
          <p v-else class="muted">14 天内无回放数据</p>
          <div class="legend">
            <span class="legend-item"><span class="dot dot-pass"></span>pass</span>
            <span class="legend-item"><span class="dot" style="background:var(--color-primary)"></span>全部</span>
          </div>
        </div>

        <!-- ③ 四分类分布（环形图）-->
        <div class="block chart-block" data-testid="donut-block">
          <h2>四分类分布（最近报告）</h2>
          <template v-if="donut && donut.total > 0">
            <div class="donut-wrap">
              <svg viewBox="0 0 140 140" class="donut-svg">
                <circle cx="70" cy="70" r="52" fill="none" stroke="var(--color-gray-2)" stroke-width="16" />
                <circle v-for="s in donut.segs" :key="s.label" cx="70" cy="70" r="52" fill="none"
                  :stroke="s.color" stroke-width="16"
                  :stroke-dasharray="s.dash" :stroke-dashoffset="s.offset"
                  transform="rotate(-90 70 70)" />
                <text x="70" y="66" text-anchor="middle" class="donut-total">{{ donut.total }}</text>
                <text x="70" y="84" text-anchor="middle" class="donut-sub">变更项</text>
              </svg>
              <div class="donut-legend">
                <div v-for="i in donut.items" :key="i.label" class="donut-legend-item">
                  <span class="legend-swatch" :style="{ background: i.color }"></span>
                  <span class="legend-label">{{ i.label }}</span>
                  <span class="legend-value">{{ i.value }}</span>
                </div>
              </div>
            </div>
          </template>
          <p v-else class="muted">暂无报告</p>
        </div>
      </div>

      <!-- ④ 最近回放活动流 -->
      <div class="block" data-testid="activity-block">
        <h2>最近回放</h2>
        <p v-if="!data.replays.recent.length" class="muted">暂无回放记录</p>
        <table v-else class="tbl">
          <thead>
            <tr><th>状态</th><th>技能</th><th>模式</th><th>耗时</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in data.replays.recent" :key="r.id">
              <td>
                <span class="dot" :class="`dot-${r.status}`"></span>{{ r.status }}
                <span v-if="r.flaky" class="badge badge-changes_requested" style="margin-left:4px">flaky</span>
              </td>
              <td>
                <RouterLink :to="`/skills/${r.skill_id}`">{{ r.skill_name }}</RouterLink>
              </td>
              <td>{{ r.mode }}</td>
              <td class="mono">{{ r.duration_ms != null ? r.duration_ms + 'ms' : '—' }}</td>
              <td class="muted">{{ fmtTime(r.ts) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dash {
  max-width: 1200px;
}
/* 统计卡排 */
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  margin-top: var(--space-6);
}
.stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}
.stat-num {
  font-size: 32px;
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: var(--color-gray-8);
}
.stat-num.ok { color: var(--color-success); }
.stat-num.warn { color: var(--color-warning); }
.stat-num.bad { color: var(--color-danger); }
.stat-label {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 500;
}
.stat-sub {
  font-size: 12px;
  color: var(--color-gray-5);
}

/* 双栏图表区 */
.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-6);
  margin-top: var(--space-6);
}
@media (max-width: 900px) {
  .grid-2 { grid-template-columns: 1fr; }
}
.chart-block { margin-top: 0; }
.trend-svg {
  width: 100%;
  height: auto;
}
.legend {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-2);
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
}

/* 环形图 */
.donut-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-6);
}
.donut-svg { width: 140px; height: 140px; }
.donut-total {
  font-size: 24px;
  font-weight: 700;
  fill: var(--color-gray-8);
}
.donut-sub {
  font-size: 11px;
  fill: var(--color-gray-5);
}
.donut-legend {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.donut-legend-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 13px;
}
.legend-swatch {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.legend-label {
  color: var(--color-text-secondary);
  min-width: 80px;
}
.legend-value {
  font-weight: 600;
  color: var(--color-gray-8);
}

/* 骨架屏 */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  margin-top: var(--space-6);
}
.skeleton-card {
  height: 90px;
  border-radius: var(--radius-lg);
  background: linear-gradient(90deg,
    var(--color-gray-2) 25%, var(--color-gray-1) 50%, var(--color-gray-2) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.2s infinite;
}
@keyframes shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
</style>
