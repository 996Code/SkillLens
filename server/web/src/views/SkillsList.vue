<script setup lang="ts">
// Task 3（S9 块C）：skill 卡片网格——GET /skills 列表 + 逐卡 /card 补断言数与 last_run 状态点。
import { onMounted, ref } from "vue";
import { getSkillCard, getSkills } from "../api";
import type { LastRun, SkillCard, SkillListItem } from "../api";

const skills = ref<SkillListItem[]>([]);
const cards = ref<Record<number, SkillCard>>({});
const loading = ref(true);
const error = ref("");

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
});
</script>

<template>
  <section>
    <h1>Skills</h1>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <p v-else-if="skills.length === 0" class="empty">
      暂无 Skill，先录制并归纳
    </p>

    <div v-else class="grid">
      <RouterLink
        v-for="s in skills"
        :key="s.id"
        :to="`/skills/${s.id}`"
        class="card"
      >
        <div class="card-head">
          <span class="skill-name">{{ s.name }}</span>
          <span class="badge" :class="s.status === 'learned' ? 'badge-learned' : 'badge-candidate'">
            {{ s.status }}
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
  </section>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}
.card {
  display: block;
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 14px 16px;
  text-decoration: none;
  color: inherit;
  background: #fff;
}
.card:hover {
  border-color: #185abc;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.skill-name {
  font-weight: 600;
}
.desc {
  color: #666;
  font-size: 13px;
  margin: 8px 0;
  min-height: 1.2em;
}
.meta {
  margin: 0;
  display: grid;
  gap: 4px;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}
.meta-row dt {
  color: #888;
}
.badge {
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
  white-space: nowrap;
}
.badge-learned {
  color: #1e7e34;
  background: #e6f4ea;
}
.badge-candidate {
  color: #555;
  background: #eee;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.dot-pass {
  background: #1e7e34;
}
.dot-fail {
  background: #c62828;
}
.dot-shadow {
  background: #9e9e9e;
}
.dot-error {
  background: #e65100;
}
.dot-none {
  background: transparent;
  border: 1px solid #ccc;
}
.muted,
.empty {
  color: #666;
}
.error {
  color: #c62828;
}
</style>
