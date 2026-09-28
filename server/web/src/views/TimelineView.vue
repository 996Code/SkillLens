<script setup lang="ts">
// S32 链路时间线：全流水线环节按时间倒序聚合（采集→对齐→Skill→回放→报告→
// 评审→LLM→夜间运行），每一步的链路、日志、输入输出统一可视化。
//   - 类型过滤 chip（全部 + 8 类型，带计数）
//   - 竖向时间轴：类型色点 + 时间 + 标题 + 摘要
//   - LLM 项点击展开：按需拉取完整 prompt/response（IO 全留存）
//   - skill/session 项提供下钻链接（详情页 / 审计页）
import { computed, onMounted, onUnmounted, ref } from "vue";
import { fetchStepScreenshot, getLlmLogDetail, getReplayRun, getTimeline } from "../api";
import type { LlmLogDetail, ReplayRunDetail, TimelineItem } from "../api";

const TYPE_META: Record<string, { label: string; color: string }> = {
  session: { label: "采集", color: "#3b82f6" },
  alignment: { label: "对齐", color: "#8b5cf6" },
  skill: { label: "Skill", color: "#10b981" },
  replay: { label: "回放", color: "#f59e0b" },
  report: { label: "报告", color: "#ef4444" },
  review: { label: "评审", color: "#ec4899" },
  llm: { label: "LLM", color: "#06b6d4" },
  agent_run: { label: "运行", color: "#64748b" },
};

const items = ref<TimelineItem[]>([]);
const loading = ref(true);
const error = ref("");

const typeFilter = ref("");
const typeCounts = computed(() => {
  const counts = new Map<string, number>();
  for (const it of items.value) counts.set(it.type, (counts.get(it.type) ?? 0) + 1);
  return counts;
});
const shown = computed(() =>
  typeFilter.value ? items.value.filter((it) => it.type === typeFilter.value) : items.value);

function typeLabel(t: string): string {
  return TYPE_META[t]?.label ?? t;
}
function typeColor(t: string): string {
  return TYPE_META[t]?.color ?? "var(--color-gray-5)";
}

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "");
}

// ---------- LLM IO 展开（按需拉取，缓存已展开项） ----------
const expandedKey = ref<string | null>(null);
const llmCache = new Map<number, LlmLogDetail>();
const llmDetail = ref<LlmLogDetail | null>(null);
const llmLoading = ref(false);
const llmError = ref("");

async function toggleItem(it: TimelineItem): Promise<void> {
  const key = `${it.type}:${it.id}`;
  if (expandedKey.value === key) {
    expandedKey.value = null;
    return;
  }
  expandedKey.value = key;
  llmDetail.value = null;
  llmError.value = "";
  replayDetail.value = null;
  replayShots.value = [];
  replayError.value = "";
  if (it.type === "llm") {
    await expandLlm(it, key);
    return;
  }
  if (it.type === "replay") {
    await loadReplay(Number(it.id), key);
  }
}

async function expandLlm(it: TimelineItem, key: string): Promise<void> {
  const id = Number(it.id);
  const cached = llmCache.get(id);
  if (cached) {
    llmDetail.value = cached;
    return;
  }
  llmLoading.value = true;
  try {
    const d = await getLlmLogDetail(id);
    llmCache.set(id, d);
    if (expandedKey.value === key) llmDetail.value = d; // 已切走则丢弃
  } catch (e) {
    if (expandedKey.value === key) llmError.value = e instanceof Error ? e.message : String(e);
  } finally {
    llmLoading.value = false;
  }
}

function detailLink(it: TimelineItem): string | null {
  if (it.type === "skill") return `/skills/${it.id}`;
  if (it.type === "session") return "/audit";
  return null;
}

// ---------- 回放步骤截图墙（S33：每次点击/输入留画面） ----------
interface ShotCard {
  file: string;
  url: string;
  caption: string;
}
const replayDetail = ref<ReplayRunDetail | null>(null);
const replayShots = ref<ShotCard[]>([]);
const replayLoading = ref(false);
const replayError = ref("");
const replayCache = new Map<number, { detail: ReplayRunDetail; shots: ShotCard[] }>();

function shotCaption(file: string, executed: Record<string, unknown>[] | null): string {
  if (file === "start.png") return "起始页";
  const step = (executed || []).find((s) => s.screenshot === file);
  if (!step) return file;
  const label = String(step.label ?? step.name ?? "");
  return `${String(step.kind ?? "")} ${label}${step.ok ? "" : "（失败）"}`;
}

async function loadReplay(id: number, key: string): Promise<void> {
  const cached = replayCache.get(id);
  if (cached) {
    replayDetail.value = cached.detail;
    replayShots.value = cached.shots;
    return;
  }
  replayLoading.value = true;
  try {
    const detail = await getReplayRun(id);
    const meta = (detail.plan as { step_screenshots?: { files: string[] } } | null)
      ?.step_screenshots;
    const shots: ShotCard[] = [];
    for (const file of meta?.files ?? []) {
      try {
        const url = await fetchStepScreenshot(id, file);
        shots.push({ file, url, caption: shotCaption(file, detail.executed) });
      } catch {
        /* 单张失败不阻塞整墙 */
      }
    }
    replayCache.set(id, { detail, shots });
    if (expandedKey.value === key) {
      replayDetail.value = detail;
      replayShots.value = shots;
    }
  } catch (e) {
    if (expandedKey.value === key) {
      replayError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    replayLoading.value = false;
  }
}

onUnmounted(() => {
  for (const { shots } of replayCache.values()) {
    for (const s of shots) URL.revokeObjectURL(s.url);
  }
});

onMounted(async () => {
  try {
    items.value = await getTimeline();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>链路时间线</h1>
    <p class="muted page-desc">
      每一次运行、每一步的链路与输入输出统一留存：采集 → 对齐 → Skill 学习 → 回放 →
      报告 → 评审，含 LLM 调用完整 IO。点击 LLM 项展开 prompt/response。
    </p>

    <div class="block">
      <!-- 类型过滤 -->
      <div class="type-filter" data-testid="type-filter">
        <button
          class="filter-chip"
          :class="{ active: typeFilter === '' }"
          @click="typeFilter = ''"
        >
          全部 {{ items.length }}
        </button>
        <button
          v-for="(meta, t) in TYPE_META"
          :key="t"
          class="filter-chip"
          :class="{ active: typeFilter === t }"
          :data-testid="`filter-${t}`"
          @click="typeFilter = typeFilter === t ? '' : t"
        >
          <span class="chip-dot" :style="{ background: meta.color }"></span>
          {{ meta.label }} {{ typeCounts.get(t) ?? 0 }}
        </button>
      </div>

      <p v-if="loading" class="muted">加载中…</p>
      <p v-else-if="error" class="error">加载失败：{{ error }}</p>
      <p v-else-if="shown.length === 0" class="muted empty-line">
        暂无链路记录，先录制一轮操作
      </p>

      <!-- 竖向时间轴 -->
      <ol v-else class="timeline" data-testid="timeline-list">
        <li
          v-for="it in shown"
          :key="`${it.type}:${it.id}`"
          class="tl-item"
          :class="{ expanded: expandedKey === `${it.type}:${it.id}` }"
          :data-testid="`tl-${it.type}`"
          @click="toggleItem(it)"
        >
          <span class="tl-dot" :style="{ background: typeColor(it.type) }"></span>
          <div class="tl-body">
            <div class="tl-head">
              <span class="badge badge-kind">{{ typeLabel(it.type) }}</span>
              <span class="tl-title">{{ it.title }}</span>
              <span class="muted tl-time">{{ fmtTime(it.ts) }}</span>
            </div>
            <div class="muted tl-sub">{{ it.subtitle }}</div>

            <!-- LLM IO 全留存展开区 -->
            <div
              v-if="expandedKey === `llm:${it.id}`"
              class="llm-detail"
              data-testid="llm-detail"
              @click.stop
            >
              <p v-if="llmLoading" class="muted">IO 加载中…</p>
              <p v-else-if="llmError" class="error">IO 加载失败：{{ llmError }}</p>
              <template v-else-if="llmDetail">
                <p class="log-head">
                  prompt（{{ llmDetail.prompt_tokens ?? "—" }} tokens）
                </p>
                <pre class="code">{{ llmDetail.prompt || "（空）" }}</pre>
                <p class="log-head">
                  response（{{ llmDetail.completion_tokens ?? "—" }} tokens ·
                  {{ llmDetail.latency_ms }}ms）
                </p>
                <pre class="code">{{ llmDetail.response || "（空）" }}</pre>
              </template>
            </div>

            <!-- 回放步骤截图墙（S33） -->
            <div
              v-if="expandedKey === `replay:${it.id}`"
              class="replay-detail"
              data-testid="replay-detail"
              @click.stop
            >
              <p v-if="replayLoading" class="muted">步骤截图加载中…</p>
              <p v-else-if="replayError" class="error">加载失败：{{ replayError }}</p>
              <template v-else-if="replayShots.length">
                <p class="muted shot-hint">
                  {{ replayDetail?.status }} · {{ replayShots.length }} 张步骤画面
                </p>
                <div class="shot-grid" data-testid="shot-grid">
                  <figure v-for="s in replayShots" :key="s.file" class="shot-card">
                    <img :src="s.url" :alt="s.caption" loading="lazy" />
                    <figcaption>{{ s.caption }}</figcaption>
                  </figure>
                </div>
              </template>
              <p v-else class="muted">该 run 无步骤截图（旧数据或采集能力缺失）</p>
            </div>

            <!-- 非 LLM/replay 项：下钻链接 -->
            <div
              v-else-if="expandedKey === `${it.type}:${it.id}` && detailLink(it)"
              class="tl-links"
              @click.stop
            >
              <RouterLink :to="detailLink(it)!" class="btn btn-secondary">
                下钻查看
              </RouterLink>
            </div>
          </div>
        </li>
      </ol>
    </div>
  </section>
</template>

<style scoped>
.empty-line {
  margin: var(--space-2) 0;
}
.type-filter {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}
.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--color-gray-3);
  background: var(--color-surface);
  color: var(--color-gray-7);
  font-size: 12px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}
.filter-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}
.filter-chip.active {
  background: var(--color-primary-soft);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: 600;
}
.chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  position: relative;
}
.timeline::before {
  content: "";
  position: absolute;
  left: 5px;
  top: 8px;
  bottom: 8px;
  width: 2px;
  background: var(--color-gray-3);
}
.tl-item {
  position: relative;
  padding: var(--space-2) 0 var(--space-2) var(--space-6);
  cursor: pointer;
  border-radius: var(--radius-md);
}
.tl-item:hover {
  background: var(--color-gray-1);
}
.tl-item.expanded {
  background: var(--color-gray-1);
}
.tl-dot {
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--color-surface);
  box-shadow: 0 0 0 1px var(--color-gray-3);
}
.tl-body {
  min-width: 0;
}
.tl-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.tl-title {
  font-weight: 600;
  font-size: 13px;
}
.tl-time {
  font-size: 12px;
  font-family: var(--font-mono);
  margin-left: auto;
  white-space: nowrap;
}
.tl-sub {
  font-size: 12px;
  margin-top: 2px;
}
.llm-detail {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
}
.log-head {
  margin: var(--space-2) 0 var(--space-1);
  font-size: 12px;
  color: var(--color-gray-5);
  font-weight: 600;
}
.llm-detail .code {
  max-height: 260px;
  overflow-y: auto;
  margin-bottom: var(--space-2);
}
.tl-links {
  margin-top: var(--space-2);
}
.replay-detail {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
}
.shot-hint {
  font-size: 12px;
  margin: 0 0 var(--space-2);
}
.shot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-3);
}
.shot-card {
  margin: 0;
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--color-gray-1);
}
.shot-card img {
  display: block;
  width: 100%;
  height: 140px;
  object-fit: cover;
  object-position: top;
  background: var(--color-gray-2);
}
.shot-card figcaption {
  padding: var(--space-1) var(--space-2);
  font-size: 12px;
  color: var(--color-gray-6);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
