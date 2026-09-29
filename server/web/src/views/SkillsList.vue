<script setup lang="ts">
// Task 3（S9 块C）：skill 卡片网格——GET /skills 列表 + 逐卡 /card 补断言数与 last_run 状态点。
// S10 Task5：卡片 source 徽标（demo 灰 / real_traffic 绿）+ 顶部基线对比区块（C2 达标态）。
import { computed, onMounted, ref } from "vue";
import { getGenericSkills, type GenericSkillItem } from "../api";
import { getBaselineCompare, getSkillCard, getSkills } from "../api";
import type { BaselineCompare, LastRun, SkillCard, SkillListItem } from "../api";

const skills = ref<SkillListItem[]>([]);
const cards = ref<Record<number, SkillCard>>({});
const loading = ref(true);
const error = ref("");
const compare = ref<BaselineCompare | null>(null);
const generics = ref<GenericSkillItem[]>([]);
const compareError = ref("");
// S28 块 Y：搜索 + 状态/来源过滤
const search = ref("");
const statusFilter = ref("all");
const sourceFilter = ref("all");

const filteredSkills = computed(() => {
  let list = skills.value;
  if (search.value.trim()) {
    const q = search.value.trim().toLowerCase();
    list = list.filter((s) => s.name.toLowerCase().includes(q)
      || s.description.toLowerCase().includes(q));
  }
  if (statusFilter.value !== "all") {
    list = list.filter((s) => s.source === statusFilter.value);
  }
  if (sourceFilter.value !== "all") {
    list = list.filter((s) => s.source === sourceFilter.value);
  }
  return list;
});

function confPct(c: number): string {
  return `${Math.round(c * 100)}%`;
}

function runDotCls(run: LastRun | null): string {
  if (!run) return "dot-none";
  return `dot-${run.status}`;
}

function runLabel(run: LastRun | null): string {
  if (!run) return "未回放";
  return `${run.status} · ${run.mode}`;
}

function sourceLabel(s: string): string {
  return s === "real_traffic" ? "真实流量" : "演示";
}

function ratioPct(r: number | null): string {
  return r === null ? "—" : `${Math.round(r * 100)}%`;
}

onMounted(async () => {
  try {
    skills.value = await getSkills();
    // 并发拉卡片补列表概要字段（断言数 / last_run）；失败不阻塞列表本身
    await Promise.all(skills.value.map(async (s) => {
      try {
        cards.value[s.id] = await getSkillCard(s.id);
      } catch {
        /* 单卡失败容忍：列表仍渲染，概要缺省 */
      }
    }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
  // 基线对比区块独立拉取：失败只降级该区块，不影响列表
  try {
    compare.value = await getBaselineCompare();
    try { generics.value = await getGenericSkills(); } catch { /* fail-open */ }
  } catch (e) {
    compareError.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<template>
  <section>
    <h1>操作流程</h1>

    <!-- S10 Task5：基线对比区块（demo vs 真实流量，C2 = 置信度比 ≥ 80%）
         S16 块 Q：升级为醒目横幅卡（主色渐变 + 左侧色条） -->
    <div v-if="compare" class="compare-banner" data-testid="baseline-compare">
      <div class="compare-head">
        <span class="compare-title">基线对比</span>
        <span
          class="badge"
          :class="compare.vs_baseline.meets_c2 ? 'c2-met' : 'c2-not'"
          data-testid="c2-status"
        >
          {{ compare.vs_baseline.meets_c2 ? "C2 达标" : "C2 未达标" }}
        </span>
      </div>
      <p v-if="compare.real_traffic.count === 0" class="compare-empty">
        暂无真实流量数据
      </p>
      <dl v-else class="compare-meta">
        <div class="meta-item">
          <dt>演示 / 真实流量</dt>
          <dd>{{ compare.demo.count }} / {{ compare.real_traffic.count }}</dd>
        </div>
        <div class="meta-item">
          <dt>置信度比</dt>
          <dd data-testid="confidence-ratio">{{ ratioPct(compare.vs_baseline.confidence_ratio) }}</dd>
        </div>
        <div class="meta-item">
          <dt>断言通过率比</dt>
          <dd>{{ ratioPct(compare.vs_baseline.pass_rate_ratio) }}</dd>
        </div>
      </dl>
    </div>
    <p v-else-if="compareError" class="muted compare-error">基线对比加载失败：{{ compareError }}</p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <div v-else-if="skills.length === 0" class="empty">
      <span class="empty-icon">◇</span>
      <p class="empty-title">暂无 Skill，先录制并归纳</p>
      <p class="empty-sub">录制一轮真实操作并完成归纳后，Skill 卡片会出现在这里</p>
    </div>

    <div v-else>
      <div class="filter-bar" data-testid="filter-bar">
        <input
          v-model="search"
          type="text"
          placeholder="搜索技能名或描述…"
          data-testid="skill-search"
        />
        <select v-model="statusFilter" data-testid="status-filter">
          <option value="all">全部状态</option>
          <option value="learned">learned</option>
          <option value="candidate">candidate</option>
        </select>
        <select v-model="sourceFilter" data-testid="source-filter">
          <option value="all">全部来源</option>
          <option value="real_traffic">真实流量</option>
          <option value="demo">演示</option>
        </select>
        <span class="muted filter-count">{{ filteredSkills.length }} / {{ skills.length }}</span>
      </div>
      <div v-if="filteredSkills.length === 0" class="empty">
        <span class="empty-icon">⌕</span>
        <p class="empty-title">无匹配技能</p>
        <p class="empty-sub">调整搜索词或过滤条件</p>
      </div>
      <div v-else class="grid">
      <RouterLink
        v-for="s in filteredSkills"
        :key="s.id"
        :to="`/graph/skill/${s.id}`"
        class="card skill-card"
      >
        <div class="card-head">
          <span class="skill-name">{{ s.name }}</span>
          <span class="badges">
            <span
              class="badge"
              :class="s.source === 'real_traffic' ? 'badge-real' : 'badge-demo'"
              data-testid="source-badge"
            >{{ sourceLabel(s.source) }}</span>
            <span class="badge" :class="s.status === 'learned' ? 'badge-learned' : 'badge-candidate'">
              {{ s.status }}
            </span>
          </span>
        </div>
        <p class="desc">{{ s.description || "（无描述）" }}</p>
        <dl class="meta">
          <div class="meta-row">
            <dt>置信度</dt>
            <dd>{{ confPct(s.confidence) }}</dd>
          </div>
          <div class="meta-row">
            <dt>证据</dt>
            <dd>{{ s.evidence_count }}</dd>
          </div>
          <div class="meta-row">
            <dt>断言</dt>
            <dd>{{ cards[s.id]?.assertions.length ?? "…" }}</dd>
          </div>
          <div class="meta-row">
            <dt>最近回放</dt>
            <dd>
              <span class="dot" :class="runDotCls(cards[s.id]?.last_run ?? null)"></span>
              {{ runLabel(cards[s.id]?.last_run ?? null) }}
            </dd>
          </div>
        </dl>
      </RouterLink>
      </div>
    </div>
  </section>

  <section v-if="generics.length" class="block" data-testid="generic-skills">
    <h2>通用能力层（跨系统 Skill）</h2>
    <table class="tbl">
      <thead><tr><th>名称</th><th>状态</th><th>源系统数</th><th>槽位</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="g in generics" :key="g.id">
          <td class="mono">{{ g.name }}</td>
          <td><span class="badge" :class="g.status === 'learned' ? 'badge-learned' : 'badge-candidate'">{{ g.status }}</span></td>
          <td>{{ g.source_skill_ids.length }}</td>
          <td>{{ g.slots_schema.length }}</td>
          <td>{{ g.description }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.filter-bar {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  margin-bottom: var(--space-4);
}
.filter-bar input {
  flex: 1;
  max-width: 280px;
}
.filter-count {
  font-size: 12px;
  white-space: nowrap;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}
.skill-card {
  padding: var(--space-3) var(--space-4);
  color: inherit;
  text-decoration: none;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}
.skill-name {
  font-weight: 600;
}
.desc {
  color: var(--color-text-secondary);
  font-size: 13px;
  margin: var(--space-2) 0;
  min-height: 1.2em;
}
.meta {
  margin: 0;
  display: grid;
  gap: var(--space-1);
}
.meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.meta-row dt {
  color: var(--color-gray-5);
}
.badges {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  min-width: 0;
}
/* 基线对比横幅卡：主色渐变 + 左色条，醒目置顶 */
.compare-banner {
  border: 1px solid var(--color-primary-border);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--space-4);
  background: linear-gradient(90deg, var(--color-primary-soft), var(--color-surface) 55%);
}
.compare-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1);
}
.compare-title {
  font-weight: 600;
}
.compare-meta {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}
.meta-item dt {
  font-size: 12px;
  color: var(--color-gray-5);
}
.meta-item dd {
  margin: 2px 0 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--color-gray-8);
}
.compare-empty {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}
.compare-error {
  font-size: 13px;
  margin-bottom: var(--space-3);
}
</style>
