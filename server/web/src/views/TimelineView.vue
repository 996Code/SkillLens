<script setup lang="ts">
// S37-2 时间线重构为**测试活动视角**：主行只有测试运行（自动测试）与
// 录制学习两类（用户视角）；内部事件（LLM/夜间运行/报告/评审）经
// "内部事件"开关附带（开发者视角）。
//   - 类型过滤 chip（带计数）
//   - 竖向时间轴：类型色点 + 时间 + 标题 + 摘要
//   - test_run 项展开：步骤截图墙 + 下钻 run 详情页
//   - recording 项展开：学到的操作流程清单（链接详情页）
//   - LLM 项展开：完整 prompt/response（IO 全留存）
import { computed, onMounted, ref } from "vue";
import { getLlmLogDetail, getReplayRun, getTimeline } from "../api";
import type { LlmLogDetail, TimelineItem } from "../api";
import { shotCaption, stepScreenshotFiles } from "../run-format";
import ShotGallery from "../components/ShotGallery.vue";
import type { ShotItem } from "../components/ShotGallery.vue";

const TYPE_META: Record<string, { label: string; color: string }> = {
  test_run: { label: "自动测试", color: "#f59e0b" },
  recording: { label: "录制学习", color: "#3b82f6" },
  llm: { label: "LLM", color: "#06b6d4" },
  agent_run: { label: "夜间运行", color: "#64748b" },
  report: { label: "报告", color: "#ef4444" },
  review: { label: "评审", color: "#ec4899" },
};

const items = ref<TimelineItem[]>([]);
const loading = ref(true);
const error = ref("");
const showInternal = ref(false);

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
  replayShots.value = [];
  replayError.value = "";
  if (it.type === "llm") {
    await expandLlm(it, key);
    return;
  }
  if (it.type === "test_run") {
    await loadReplay(Number(it.id), key);
  }
  // recording：skills 清单已在 it.skills，展开即渲染（无需拉取）
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



// ---------- 回放步骤截图墙（S33/S34：ShotGallery 组件承载，含点击放大） ----------
const replayShots = ref<ShotItem[]>([]);
const replayLoading = ref(false);
const replayError = ref("");
const replayCache = new Map<number, ShotItem[]>();

async function loadReplay(id: number, key: string): Promise<void> {
  const cached = replayCache.get(id);
  if (cached) {
    replayShots.value = cached;
    return;
  }
  replayLoading.value = true;
  try {
    const detail = await getReplayRun(id);
    const meta = stepScreenshotFiles(detail.plan);
    const shots: ShotItem[] = (meta?.files ?? []).map((file) => ({
      file, caption: shotCaption(file, detail.executed),
    }));
    replayCache.set(id, shots);
    if (expandedKey.value === key) replayShots.value = shots;
  } catch (e) {
    if (expandedKey.value === key) {
      replayError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    replayLoading.value = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    items.value = await getTimeline(100, showInternal.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function toggleInternal(): Promise<void> {
  showInternal.value = !showInternal.value;
  expandedKey.value = null;
  await load();
}

onMounted(() => void load());
</script>

<template>
  <section>
    <h1>测试活动</h1>
    <p class="muted page-desc">
      每一次自动测试与录制学习的完整记录：点开看步骤截图、学到的操作流程与
      LLM 输入输出。内部事件（对齐/LLM 调用等）可按需展开。
    </p>

    <div class="block">
      <!-- 内部事件开关 + 类型过滤 -->
      <div class="view-controls">
        <label class="internal-toggle" data-testid="internal-toggle">
          <input :checked="showInternal" type="checkbox" @change="toggleInternal" />
          显示内部事件（LLM/对齐等）
        </label>
      </div>
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
        暂无测试活动，先录制一轮操作
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

            <!-- 测试运行步骤截图墙（S33/S34：ShotGallery 含点击放大） -->
            <div
              v-if="expandedKey === `test_run:${it.id}`"
              class="replay-detail"
              data-testid="replay-detail"
              @click.stop
            >
              <p v-if="replayLoading" class="muted">步骤截图加载中…</p>
              <p v-else-if="replayError" class="error">加载失败：{{ replayError }}</p>
              <template v-else>
                <p class="muted shot-hint">{{ replayShots.length }} 张步骤画面</p>
                <div class="shot-links">
                  <RouterLink :to="`/graph/run/${it.id}`" class="btn btn-secondary">
                    下钻 run 详情
                  </RouterLink>
                </div>
                <ShotGallery :run-id="it.id" :items="replayShots" />
              </template>
            </div>

            <!-- 录制学习：学到的操作流程清单 -->
            <div
              v-else-if="expandedKey === `recording:${it.id}`"
              class="rec-detail"
              data-testid="rec-detail"
              @click.stop
            >
              <p class="muted shot-hint">学到的操作流程（{{ (it.skills || []).length }}）</p>
              <ul class="skill-list">
                <li v-for="s in it.skills || []" :key="s.id">
                  <RouterLink :to="`/graph/skill/${s.id}`">{{ s.name }}</RouterLink>
                </li>
              </ul>
              <div class="shot-links">
                <RouterLink to="/graph" class="btn btn-secondary">
                  查看全部操作流程
                </RouterLink>
              </div>
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
.view-controls {
  margin-bottom: var(--space-2);
}
.internal-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--color-gray-6);
  cursor: pointer;
}
.rec-detail {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
}
.skill-list {
  list-style: none;
  margin: 0 0 var(--space-2);
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  font-size: 13px;
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
.shot-links {
  margin-bottom: var(--space-2);
}
</style>
