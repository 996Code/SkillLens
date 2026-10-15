<script setup lang="ts">
// 系统总览 v3（UI 优化批1）：仪表盘门面——S28 /dashboard 端点此前无前端
// 消费（"功能设计了但没用起来"体检首例），本页接上：指标卡带 + 14 天
// 趋势 + 系统健康（trends）+ 最近运行 + 流水线图。假节点色条预览墙移除。
import { computed, onMounted, ref } from "vue";
import { getSkills, listSuites, getDashboard, getSystemTrends, listScenarios } from "../../api";
import type { ScenarioListItem } from "../../api";
import type { SkillListItem, SuiteItem, DashboardPayload, SystemTrend } from "../../api";
import { systemColor } from "../../system-group";

const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const dash = ref<DashboardPayload | null>(null);
const trends = ref<SystemTrend[]>([]);
// AQ3：场景卡（替代流水线区）
const scenarios = ref<ScenarioListItem[]>([]);
// S43-2：流水线卡片"批量测试"节点的子图展开态
const expanded = ref<Record<number, boolean>>({});
const loading = ref(true);
const error = ref("");

const passRate = computed(() => {
  const r = dash.value?.replays;
  if (!r || !(r.pass + r.fail + r.error)) return null;
  return Math.round((r.pass / (r.pass + r.fail + r.error)) * 100);
});

// 14 天趋势柱图（纯确定性渲染——无图表库依赖）
const trendView = computed(() => {
  const t = dash.value?.trend ?? [];
  const max = Math.max(1, ...t.map((d) => d.total));
  return t.map((d) => ({
    ...d,
    h: Math.max(2, Math.round((d.total / max) * 56)),
    ph: Math.max(1, Math.round((d.pass / max) * 56)),
    label: d.date.slice(5),
  }));
});

// trends API 的 rate 是 0-1 小数，展示层换算为百分数
const pct = (r: number) => Math.round(r * 100);

const rateTone = (rate: number) =>
  rate >= 90 ? "pass" : rate >= 60 ? "warn" : "fail";

function fmtDuration(ms: number | null): string {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

function fmtAgo(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  return `${Math.floor(h / 24)} 天前`;
}

onMounted(async () => {
  try {
    const [s, sk, d, t, c] = await Promise.all([
      listSuites(), getSkills(), getDashboard(), getSystemTrends(), listScenarios(),
    ]);
    suites.value = s;
    skills.value = sk;
    dash.value = d;
    trends.value = t;
    scenarios.value = c;
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
    <p class="muted page-desc">技能库健康度、执行趋势与最近运行。</p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <!-- 指标卡带 -->
      <div class="metric-grid" data-testid="overview-metrics">
        <div class="metric-card">
          <span class="metric-label">技能库存</span>
          <span class="metric-value">{{ dash?.skills.total ?? "—" }}</span>
          <span class="metric-sub muted">
            learned {{ dash?.skills.learned ?? 0 }} · candidate {{ dash?.skills.candidate ?? 0 }}
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-label">总通过率</span>
          <span class="metric-value" :class="passRate === null ? '' : `tone-${rateTone(passRate)}`">
            {{ passRate === null ? "—" : `${passRate}%` }}
          </span>
          <span class="metric-sub muted">
            {{ dash?.replays.total ?? 0 }} 次回放 · flaky {{ dash?.replays.flaky ?? 0 }}
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-label">累计失败</span>
          <span class="metric-value tone-fail">{{ dash?.replays.fail ?? 0 }}</span>
          <span class="metric-sub muted">
            error {{ dash?.replays.error ?? 0 }} · shadow {{ dash?.replays.shadow ?? 0 }}
          </span>
        </div>
        <div class="metric-card">
          <span class="metric-label">四分类报告</span>
          <span class="metric-value">{{ dash?.reports.total ?? 0 }}</span>
          <span class="metric-sub muted">流水线 {{ suites.length }} 组 · 技能 {{ skills.length }}</span>
        </div>
      </div>

      <!-- 14 天趋势 + 系统健康 -->
      <div class="dash-row">
        <div class="block dash-trend">
          <h2>近 14 天执行趋势</h2>
          <p v-if="!trendView.length" class="muted">暂无回放数据</p>
          <div v-else class="trend-chart" data-testid="overview-trend">
            <div v-for="d in trendView" :key="d.date" class="trend-col"
                 :title="`${d.date}：${d.total} 次（pass ${d.pass}）`">
              <div class="trend-bar-wrap">
                <div class="trend-bar" :style="{ height: `${d.h}px` }"></div>
                <div class="trend-bar pass" :style="{ height: `${d.ph}px` }"></div>
              </div>
              <span class="trend-label">{{ d.label }}</span>
            </div>
          </div>
        </div>
        <div class="block dash-systems">
          <h2>系统健康（近 30 天）</h2>
          <p v-if="!trends.length" class="muted">暂无回放数据</p>
          <div v-else class="sys-health-list" data-testid="overview-systems">
            <div v-for="t in trends" :key="t.system" class="sys-health-row">
              <span class="sys-dot" :style="{ background: systemColor(t.system) }"></span>
              <span class="sys-health-name">{{ t.system }}</span>
              <div class="sys-health-bar">
                <div class="sys-health-fill" :class="`tone-bg-${rateTone(pct(t.rate))}`"
                     :style="{ width: `${pct(t.rate)}%` }"></div>
              </div>
              <span class="sys-health-rate" :class="`tone-${rateTone(pct(t.rate))}`">{{ pct(t.rate) }}%</span>
              <span class="muted sys-health-runs">{{ t.total }} 次</span>
              <span v-if="t.unverified_pass" class="chip warn"
                    :title="`${t.unverified_pass} 次 pass 无断言佐证`">
                无断言 {{ t.unverified_pass }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- 最近运行 -->
      <div class="block">
        <h2>最近运行</h2>
        <p v-if="!dash?.replays.recent.length" class="muted">暂无运行</p>
        <table v-else class="tbl" data-testid="overview-recent">
          <thead>
            <tr><th>Run</th><th>技能</th><th>状态</th><th>模式</th><th>耗时</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in dash!.replays.recent" :key="r.id">
              <td>
                <RouterLink :to="`/graph/run/${r.id}`">#{{ r.id }}</RouterLink>
              </td>
              <td>
                <RouterLink :to="`/graph/skill/${r.skill_id}`">{{ r.skill_name }}</RouterLink>
              </td>
              <td>
                <span class="badge" :class="`badge-${r.status}`">
                  {{ r.status }}<template v-if="r.flaky"> ·flaky</template>
                </span>
              </td>
              <td class="muted">{{ r.mode }}</td>
              <td class="muted">{{ fmtDuration(r.duration_ms) }}</td>
              <td class="muted">{{ fmtAgo(r.ts) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- AQ3：测试场景（用户工作层——替代流水线区） -->
      <div class="block" data-testid="overview-scenarios">
        <h2>测试场景（{{ scenarios.length }}）</h2>
        <p v-if="!scenarios.length" class="muted">
          暂无场景，去
          <RouterLink to="/graph/scenarios">测试场景</RouterLink> 查看
        </p>
        <div v-else class="scenario-grid">
          <RouterLink v-for="c in scenarios.slice(0, 12)" :key="c.id"
                      :to="`/graph/scenario/${c.id}`"
                      class="overview-scenario-card"
                      :data-testid="`overview-scenario-${c.id}`">
            <span class="overview-scenario-name">{{ c.name }}</span>
            <span class="muted overview-scenario-meta">{{ c.system }} · {{ c.steps.length }} 步</span>
          </RouterLink>
          <RouterLink v-if="scenarios.length > 12" to="/graph/scenarios"
                      class="overview-scenario-card overview-scenario-more">
            查看全部 {{ scenarios.length }} 个场景 →
          </RouterLink>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.metric-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-4) var(--space-5);
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
  overflow: hidden;
  transition: box-shadow var(--dur-mid) var(--ease-out),
    transform var(--dur-mid) var(--ease-out);
}
.metric-card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.metric-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--color-primary),
    var(--color-primary-border));
  opacity: 0.85;
}
.metric-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--color-gray-5);
}
.metric-value {
  font-size: 30px;
  font-weight: 750;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}
.metric-value.tone-pass { color: var(--color-success, #16a34a); }
.metric-value.tone-warn { color: var(--color-warning, #d97706); }
.metric-value.tone-fail { color: var(--color-danger, #dc2626); }
.metric-sub { font-size: 12px; }

.dash-row {
  display: grid;
  grid-template-columns: minmax(320px, 5fr) minmax(320px, 4fr);
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  align-items: start;
}
@media (max-width: 1000px) {
  .dash-row { grid-template-columns: 1fr; }
}
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 6px;
  height: 84px;
  padding-top: var(--space-2);
}
.trend-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.trend-bar-wrap {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 60px;
}
.trend-bar {
  width: 10px;
  border-radius: 2px 2px 0 0;
  background: var(--color-danger-soft, #fecaca);
}
.trend-bar.pass {
  background: var(--color-success, #16a34a);
}
.trend-label {
  font-size: 10px;
  color: var(--color-gray-5);
  white-space: nowrap;
}
.sys-health-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.sys-health-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.sys-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  flex: none;
}
.sys-health-name {
  width: 90px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sys-health-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: var(--color-gray-2, #eef2f7);
  overflow: hidden;
}
.sys-health-fill {
  height: 100%;
  border-radius: 4px;
}
.sys-health-fill.tone-bg-pass { background: var(--color-success, #16a34a); }
.sys-health-fill.tone-bg-warn { background: var(--color-warning, #d97706); }
.sys-health-fill.tone-bg-fail { background: var(--color-danger, #dc2626); }
.sys-health-rate {
  width: 44px;
  text-align: right;
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.sys-health-rate.tone-pass { color: var(--color-success, #16a34a); }
.sys-health-rate.tone-warn { color: var(--color-warning, #d97706); }
.sys-health-rate.tone-fail { color: var(--color-danger, #dc2626); }
.sys-health-runs { font-size: 12px; width: 48px; text-align: right; }
.chip.warn { background: var(--color-warning-soft, #fef3c7); }

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
/* S43-2：批量测试节点可点展开子图 */
.pipe-batch {
  cursor: pointer;
}
.pipe-batch:hover rect {
  stroke-width: 2.5;
}
.pipe-subflow {
  margin: var(--space-1) 0 var(--space-2);
  padding: var(--space-2);
  border: 1px dashed var(--color-warning);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pipe-sub-leaf {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  text-decoration: none;
  color: var(--color-text);
}
.pipe-sub-leaf:hover {
  text-decoration: underline;
}
</style>

/* AQ3：总览场景卡 */
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-2);
}
.overview-scenario-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  text-decoration: none;
  color: inherit;
  transition: border-color var(--dur-fast) ease,
    box-shadow var(--dur-fast) ease;
}
.overview-scenario-card:hover {
  border-color: var(--color-primary-border);
  box-shadow: var(--shadow-sm);
  text-decoration: none;
}
.overview-scenario-name {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}
.overview-scenario-meta {
  font-size: 11.5px;
}
.overview-scenario-more {
  justify-content: center;
  align-items: center;
  color: var(--color-primary);
  font-weight: 600;
}
