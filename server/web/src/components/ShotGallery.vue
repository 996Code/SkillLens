<script setup lang="ts">
// S34：步骤截图墙共享组件——网格缩略图 + 点击放大（lightbox）。
// 自取图（fetchStepScreenshot blob URL），卸载/换源时 revoke；
// 单张失败跳过不阻塞整墙（fail-open，同 S33 语义）。
import { onUnmounted, ref, watch } from "vue";
import { fetchStepScreenshot } from "../api";

export interface ShotItem {
  file: string;
  caption: string;
}

const props = defineProps<{
  runId: number | string;
  items: ShotItem[];
}>();

const urls = ref<Record<string, string>>({});
const loading = ref(false);
const zoomed = ref<string | null>(null); // file 名

async function load(): Promise<void> {
  for (const [, u] of Object.entries(urls.value)) URL.revokeObjectURL(u);
  urls.value = {};
  if (!props.items.length) return;
  loading.value = true;
  try {
    for (const it of props.items) {
      try {
        urls.value[it.file] = await fetchStepScreenshot(props.runId, it.file);
      } catch {
        /* 单张失败不阻塞整墙 */
      }
    }
  } finally {
    loading.value = false;
  }
}

watch(() => [props.runId, props.items], () => void load(), { immediate: true });

onUnmounted(() => {
  for (const [, u] of Object.entries(urls.value)) URL.revokeObjectURL(u);
});

function openZoom(file: string): void {
  if (urls.value[file]) zoomed.value = file;
}
</script>

<template>
  <p v-if="loading" class="muted">步骤截图加载中…</p>
  <div v-else-if="items.length" class="shot-grid" data-testid="shot-grid">
    <figure
      v-for="it in items"
      :key="it.file"
      class="shot-card"
      @click="openZoom(it.file)"
    >
      <img
        v-if="urls[it.file]"
        :src="urls[it.file]"
        :alt="it.caption"
        loading="lazy"
      />
      <div v-else class="shot-missing">截图缺失</div>
      <figcaption>{{ it.caption }}</figcaption>
    </figure>
  </div>
  <p v-else class="muted">无步骤截图（旧数据或采集能力缺失）</p>

  <!-- lightbox：点击遮罩或图关闭 -->
  <Teleport to="body">
    <div
      v-if="zoomed"
      class="lightbox"
      data-testid="shot-lightbox"
      @click="zoomed = null"
    >
      <img :src="urls[zoomed]" :alt="zoomed" />
      <p class="lightbox-caption">{{ items.find((i) => i.file === zoomed)?.caption }}</p>
    </div>
  </Teleport>
</template>

<style scoped>
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
  cursor: zoom-in;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.shot-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
}
.shot-card img {
  display: block;
  width: 100%;
  height: 140px;
  object-fit: cover;
  object-position: top;
  background: var(--color-gray-2);
}
.shot-missing {
  height: 140px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-gray-5);
  font-size: 12px;
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
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(17, 24, 39, 0.85);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
  padding: var(--space-6);
}
.lightbox img {
  max-width: 92vw;
  max-height: 84vh;
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
}
.lightbox-caption {
  margin: var(--space-3) 0 0;
  color: #e5e7eb;
  font-size: 13px;
}
</style>
