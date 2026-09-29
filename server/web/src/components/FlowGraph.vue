<script setup lang="ts">
// S38 统一流程图组件（只读）：节点+边+执行注记渲染。
// 全系统流程图基座——Run 执行图 / Skill 流程图 / 套件流水线图共用。
// 节点类型着色：page 蓝 / action 按执行结果 / state 紫 / assert 按结果；
// 点击节点 → 详情面板（截图/IO/错误）。
import { computed, ref } from "vue";
import { VueFlow } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import "@vue-flow/core/dist/style.css";
import "@vue-flow/core/dist/theme-default.css";
import { fetchStepScreenshot } from "../api";

export interface FlowNode {
  id: string;
  type: string; // page | action | state | assert | skill_source | replay_batch | aggregate
  label: string;
  status: string; // ok | fail | skipped | pending | pass | shadow
  screenshot?: string;
  io?: Record<string, unknown>;
}
export interface FlowEdge {
  from: string;
  to: string;
}

const props = defineProps<{
  nodes: FlowNode[];
  edges: FlowEdge[];
  runId?: number | string; // 有值时截图可加载
}>();

const selected = ref<FlowNode | null>(null);
const shotUrl = ref<string | null>(null);

const STATUS_COLOR: Record<string, string> = {
  ok: "#16a34a", pass: "#16a34a",
  fail: "#dc2626",
  skipped: "#9ca3af", shadow: "#9ca3af", pending: "#d1d5db",
};
const TYPE_COLOR: Record<string, string> = {
  page: "#3b82f6", state: "#8b5cf6",
  skill_source: "#3b82f6", replay_batch: "#f59e0b", aggregate: "#64748b",
};

function nodeColor(n: FlowNode): string {
  return STATUS_COLOR[n.status] ?? TYPE_COLOR[n.type] ?? "#64748b";
}

const NODE_W = 190;
const NODE_H = 54;

// 线性布局：主链横排；assert 节点挂在对应位置下方
const positions = computed(() => {
  const pos: Record<string, { x: number; y: number }> = {};
  let main = 0;
  let sub = 0;
  for (const n of props.nodes) {
    if (n.type === "assert") {
      pos[n.id] = { x: 60 + sub * (NODE_W + 30), y: 200 };
      sub += 1;
    } else {
      pos[n.id] = { x: 60 + main * (NODE_W + 30), y: 80 };
      main += 1;
    }
  }
  return pos;
});

const vfNodes = computed(() =>
  props.nodes.map((n) => ({
    id: n.id,
    position: positions.value[n.id] ?? { x: 0, y: 0 },
    data: { label: n.label },
    style: {
      width: `${NODE_W}px`,
      padding: "8px 10px",
      borderRadius: "8px",
      border: `2px solid ${nodeColor(n)}`,
      background: n.status === "fail" ? "#fef2f2" : "#ffffff",
      fontSize: "12px",
      cursor: "pointer",
    },
    _flow: n,
  })),
);

const vfEdges = computed(() =>
  props.edges.map((e) => ({
    id: `${e.from}-${e.to}`,
    source: e.from,
    target: e.to,
    animated: false,
  })),
);

async function onNodeClick({ node }: { node: { id: string } }): Promise<void> {
  const n = props.nodes.find((x) => x.id === node.id);
  if (!n) return;
  selected.value = n;
  shotUrl.value = null;
  if (n.screenshot && props.runId != null) {
    try {
      shotUrl.value = await fetchStepScreenshot(props.runId, n.screenshot);
    } catch {
      /* 截图缺失不阻塞 */
    }
  }
}
</script>

<template>
  <div class="flow-graph" data-testid="flow-graph">
    <div class="fg-canvas">
      <VueFlow :nodes="vfNodes" :edges="vfEdges" :nodes-connectable="false"
               :edges-updatable="false" @node-click="onNodeClick">
        <Background pattern-color="#e5e7eb" :gap="16" />
        <Controls position="bottom-left" />
      </VueFlow>
    </div>

    <!-- 节点详情面板 -->
    <div v-if="selected" class="fg-detail" data-testid="fg-detail">
      <div class="fg-detail-head">
        <span class="badge badge-kind">{{ selected.type }}</span>
        <span class="fg-detail-label">{{ selected.label }}</span>
        <button class="fg-close" @click="selected = null">×</button>
      </div>
      <img v-if="shotUrl" :src="shotUrl" class="fg-shot" alt="步骤截图" />
      <p v-else-if="selected.screenshot" class="muted">截图缺失</p>
      <pre v-if="selected.io && Object.keys(selected.io).length"
           class="code fg-io">{{ JSON.stringify(selected.io, null, 2) }}</pre>
    </div>

    <!-- 图例 -->
    <div class="fg-legend">
      <span><i style="background:#16a34a"></i>通过</span>
      <span><i style="background:#dc2626"></i>失败</span>
      <span><i style="background:#9ca3af"></i>跳过/预演</span>
      <span><i style="background:#3b82f6"></i>页面</span>
      <span><i style="background:#8b5cf6"></i>业务状态</span>
    </div>
  </div>
</template>

<style scoped>
.flow-graph {
  position: relative;
}
.fg-canvas {
  height: 320px;
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
  background: var(--color-gray-1);
}
.fg-detail {
  margin-top: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
}
.fg-detail-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.fg-detail-label {
  font-weight: 600;
  font-size: 13px;
}
.fg-close {
  margin-left: auto;
  border: none;
  background: none;
  font-size: 18px;
  cursor: pointer;
  color: var(--color-gray-5);
}
.fg-shot {
  max-width: 100%;
  max-height: 300px;
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
}
.fg-io {
  max-height: 160px;
  overflow-y: auto;
  font-size: 12px;
}
.fg-legend {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-2);
  font-size: 12px;
  color: var(--color-gray-6);
}
.fg-legend span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.fg-legend i {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
</style>
