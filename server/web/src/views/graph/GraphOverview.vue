<script setup lang="ts">
// 系统总览 v3（UI 优化批1）：仪表盘门面——S28 /dashboard 端点此前无前端
// 消费（"功能设计了但没用起来"体检首例），本页接上：指标卡带 + 14 天
// 趋势 + 系统健康（trends）+ 最近运行 + 流水线图。假节点色条预览墙移除。
import { computed, onMounted, ref } from "vue";
import { getSkills, listSuites, getDashboard, getSystemTrends } from "../../api";
import type { SkillListItem, SuiteItem, DashboardPayload, SystemTrend } from "../../api";
import { systemColor } from "../../system-group";

const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const dash = ref<DashboardPayload | null>(null);
const trends = ref<SystemTrend[]>([]);
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
    const [s, sk, d, t] = await Promise.all([
      listSuites(), getSkills(), getDashboard(), getSystemTrends(),
    ]);
    suites.value = s;
    skills.value = sk;
    dash.value = d;
    trends.value = t;
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
                <div class="sys-health-fill" :class="`tone-bg-${rateTone(t.rate)}`"
                     :style="{ width: `${t.rate}%` }"></div>
              </div>
              <span class="sys-health-rate" :class="`tone-${rateTone(t.rate)}`">{{ t.rate }}%</span>
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

      <!-- 流水线：内嵌 SVG 流程图（保留） -->
      <div class="block" data-testid="overview-pipelines">
        <h2>流水线（{{ suites.length }}）</h2>
        <p v-if="!suites.length" class="muted">
          暂无流水线，去
          <RouterLink to="/graph/suites">分组管理</RouterLink> 创建
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
                <!-- S43-2：点"批量测试"展开流程子图（图内下钻，不跳分组页） -->
                <g class="pipe-batch" :data-testid="`pipe-batch-${s.id}`"
                   @click="expanded[s.id] = !expanded[s.id]">
                  <rect x="115" y="15" width="70" height="30" rx="6"
                        fill="var(--color-warning-soft)" stroke="var(--color-warning)" stroke-width="1.5"/>
                  <text x="150" y="35" text-anchor="middle" font-size="10" fill="var(--color-warning)">
                    批量测试{{ expanded[s.id] ? " ▾" : " ▸" }}
                  </text>
                </g>
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
            <!-- 展开的流程子图（子技能清单） -->
            <div v-if="expanded[s.id]" class="pipe-subflow" :data-testid="`pipe-subflow-${s.id}`">
              <RouterLink v-for="sk in s.skills" :key="sk.id"
                          :to="`/graph/skill/${sk.id}`" class="pipe-sub-leaf">
                <span class="dot" :class="`dot-${sk.status === 'learned' ? 'pass' : 'fail'}`"></span>
                #{{ sk.id }} {{ sk.name }}
                <span class="chip">{{ sk.system }}</span>
              </RouterLink>
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
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-label {
  font-size: 12px;
  color: var(--color-gray-6);
}
.metric-value {
  font-size: 28px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
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
