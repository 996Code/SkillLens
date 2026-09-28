<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { VueFlow, Handle } from "@vue-flow/core";
import { Background } from "@vue-flow/background";
import { Controls } from "@vue-flow/controls";
import { MiniMap } from "@vue-flow/minimap";
import { getAgentRun, getCanvas, listCanvasRuns, listCanvases, runCanvas, saveCanvas } from "../api";
import type { AgentRunDetail, CanvasEdge, CanvasNode } from "../api";

const NODE_TYPES = [
  { type: "change_source", label: "变更集源", desc: "api_templates", icon: "◈", color: "#4f46e5" },
  { type: "impact_select", label: "Impact", desc: "反查受影响 skill", icon: "⬡", color: "#0ea5e9" },
  { type: "replay_batch", label: "批回放", desc: "批量回放", icon: "▶", color: "#16a34a" },
  { type: "aggregate", label: "聚合", desc: "结果计数", icon: "Σ", color: "#d97706" },
  { type: "review_output", label: "评审输出", desc: "markdown 摘要", icon: "✓", color: "#7c3aed" },
];
function typeMeta(t) {
  return NODE_TYPES.find((x) => x.type === t) || { type: t, label: t, desc: "", icon: "◇", color: "#6b7280" };
}

const canvases = ref([]);
const canvasesLoading = ref(true);
const canvasesError = ref("");
const selectedCanvasId = ref("");
const currentCanvasId = ref(null);
const name = ref("");
const flowNodes = ref([]);
const flowEdges = ref([]);
let nodeSeq = 0;
const selectedNodeId = ref(null);
const saving = ref(false);
const saveError = ref("");
const savedHint = ref("");
const running = ref(false);
const runError = ref("");
const runHint = ref("");
const lastRun = ref(null);
const runs = ref([]);

function toFlowNodes(nodes) {
  return nodes.map((n) => ({ id: n.id, position: { x: n.x, y: n.y }, data: { type: n.type, params: n.params }, type: "custom" }));
}
function toCanvasNodes() {
  return flowNodes.value.map((fn) => {
    const d = fn.data;
    return { id: fn.id, type: d.type, params: d.params, x: fn.position.x, y: fn.position.y };
  });
}
function toFlowEdges(edges) {
  return edges.map((e, i) => ({ id: "e"+i, source: e.from, target: e.to, animated: true }));
}
function toCanvasEdges() {
  return flowEdges.value.map((e) => ({ from: e.source, to: e.target }));
}

const selectedNode = computed(() => {
  const fn = flowNodes.value.find((n) => n.id === selectedNodeId.value);
  if (!fn) return null;
  const d = fn.data;
  return { id: fn.id, type: d.type, params: d.params, x: fn.position.x, y: fn.position.y };
});

const apiTemplatesText = computed({
  get: () => ((selectedNode.value?.params.api_templates) || []).join("\n"),
  set: (v) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.api_templates = v.split(/\n|,/).map((s) => s.trim()).filter(Boolean);
  },
});
const anchorLabelsText = computed({
  get: () => ((selectedNode.value?.params.anchor_labels) || []).join("\n"),
  set: (v) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.anchor_labels = v.split(/\n|,/).map((s) => s.trim()).filter(Boolean);
  },
});
const confirmSideEffect = computed({
  get: () => selectedNode.value?.params.confirm_side_effect === true,
  set: (v) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.confirm_side_effect = v;
  },
});

function addNode(type) {
  nodeSeq += 1;
  flowNodes.value.push({
    id: "n"+nodeSeq,
    position: { x: 80 + (nodeSeq % 4) * 220, y: 80 + Math.floor(nodeSeq / 4) * 140 },
    data: { type, params: {} }, type: "custom",
  });
}
function onNodeClick({ node }) { selectedNodeId.value = node.id; }
function onConnect(conn) {
  flowEdges.value.push({ id: "e"+flowEdges.value.length, source: conn.source, target: conn.target, animated: true });
}
function removeNode(id) {
  flowNodes.value = flowNodes.value.filter((n) => n.id !== id);
  flowEdges.value = flowEdges.value.filter((e) => e.source !== id && e.target !== id);
  if (selectedNodeId.value === id) selectedNodeId.value = null;
}
function nodeClass(id) {
  const hasOut = (lastRun.value?.node_outputs || []).some((s) => s.node === id);
  if (lastRun.value?.error_text && !hasOut) return "vf-error";
  if (hasOut) return "vf-ok";
  return "";
}
function nodeArtifact(id) {
  return (lastRun.value?.node_outputs || []).find((s) => s.node === id) || null;
}
function dagPayload() { return { nodes: toCanvasNodes(), edges: toCanvasEdges() }; }
async function onSave() {
  if (!name.value.trim()) { saveError.value = "请输入名称"; return; }
  saving.value = true; saveError.value = ""; savedHint.value = "";
  try {
    const saved = await saveCanvas(name.value.trim(), dagPayload());
    currentCanvasId.value = saved.id;
    selectedCanvasId.value = String(saved.id);
    savedHint.value = "已保存 #"+saved.id;
    canvases.value = await listCanvases();
  } catch (e) { saveError.value = e instanceof Error ? e.message : String(e); }
  finally { saving.value = false; }
}
async function onRun() {
  if (currentCanvasId.value == null) { runError.value = "请先保存"; return; }
  running.value = true; runError.value = ""; runHint.value = "运行中…";
  lastRun.value = null;
  try {
    const resp = await runCanvas(currentCanvasId.value);
    lastRun.value = await getAgentRun(resp.id);
    runHint.value = "运行完成："+lastRun.value.status;
    runs.value = await listCanvasRuns(currentCanvasId.value);
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e); runHint.value = "";
  } finally { running.value = false; }
}
async function onSelectCanvas() {
  saveError.value = ""; runError.value = ""; runHint.value = ""; savedHint.value = "";
  lastRun.value = null; runs.value = []; selectedNodeId.value = null;
  if (!selectedCanvasId.value) {
    name.value = ""; flowNodes.value = []; flowEdges.value = []; nodeSeq = 0;
    currentCanvasId.value = null; return;
  }
  try {
    const d = await getCanvas(selectedCanvasId.value);
    name.value = d.name;
    flowNodes.value = toFlowNodes(d.dag.nodes);
    flowEdges.value = toFlowEdges(d.dag.edges);
    nodeSeq = d.dag.nodes.length;
    currentCanvasId.value = d.id;
  } catch (e) { saveError.value = e instanceof Error ? e.message : String(e); }
}
onMounted(async () => {
  try { canvases.value = await listCanvases(); }
  catch (e) { canvasesError.value = e instanceof Error ? e.message : String(e); }
  finally { canvasesLoading.value = false; }
});
</script>

<template>
  <section class="canvas-page">
    <h1>画布</h1>
    <p class="muted page-desc">节点式流水线编排——拖拽节点、端口连线、缩放平移、小地图导航</p>
    <div class="toolbar" data-testid="canvas-toolbar">
      <label>画布
        <select v-model="selectedCanvasId" data-testid="canvas-select" @change="onSelectCanvas">
          <option value="">新建画布</option>
          <option v-for="c in canvases" :key="c.id" :value="String(c.id)">#{{ c.id }} {{ c.name }}</option>
        </select>
      </label>
      <label>名称
        <input v-model="name" type="text" placeholder="画布名称" data-testid="canvas-name" />
      </label>
      <button type="button" class="btn btn-secondary" data-testid="save-btn" :disabled="saving" @click="onSave">保存</button>
      <button type="button" class="btn btn-primary" data-testid="run-btn" :disabled="running" @click="onRun">运行</button>
      <span v-if="savedHint" class="muted">{{ savedHint }}</span>
      <span v-if="runHint" class="run-hint" data-testid="run-hint">{{ runHint }}</span>
    </div>
    <p v-if="canvasesLoading" class="muted">加载中…</p>
    <p v-else-if="canvasesError" class="error">{{ canvasesError }}</p>
    <p v-if="saveError" class="error" data-testid="save-error">{{ saveError }}</p>
    <p v-if="runError" class="error" data-testid="run-error">{{ runError }}</p>
    <div class="canvas-layout">
      <div class="palette" data-testid="node-palette">
        <h2>节点</h2>
        <div v-for="t in NODE_TYPES" :key="t.type" class="palette-card"
             :data-testid="'palette-'+t.type" @click="addNode(t.type)">
          <span class="palette-icon" :style="{ color: t.color }">{{ t.icon }}</span>
          <div class="palette-text">
            <span class="palette-label">{{ t.label }}</span>
            <span class="muted palette-desc">{{ t.desc }}</span>
          </div>
        </div>
      </div>
      <div class="canvas-wrap" data-testid="canvas-svg">
        <VueFlow :nodes="flowNodes" :edges="flowEdges" :min-zoom="0.3" :max-zoom="2"
                 fit-view-on-init @node-click="onNodeClick" @connect="onConnect">
          <Background :gap="20" :size="1" pattern-color="#e5e7eb" />
          <Controls />
          <MiniMap />
          <template #node-custom="props">
            <div class="vf-card" :class="[nodeClass(props.id), { 'vf-selected': selectedNodeId === props.id }]">
              <div class="vf-header" :style="{ background: typeMeta(props.data.type).color + '15' }">
                <span class="vf-icon" :style="{ color: typeMeta(props.data.type).color }">{{ typeMeta(props.data.type).icon }}</span>
                <span class="vf-title">{{ typeMeta(props.data.type).label }}</span>
                <span v-if="nodeArtifact(props.id)" class="vf-status-dot ok"></span>
              </div>
              <div class="vf-body">
                <span class="vf-desc muted">{{ typeMeta(props.data.type).desc }}</span>
              </div>
              <Handle type="source" :position="'right'" />
              <Handle type="target" :position="'left'" />
              <button v-if="selectedNodeId === props.id" class="vf-del"
                      data-testid="node-delete" @click.stop="removeNode(props.id)">x</button>
            </div>
          </template>
        </VueFlow>
      </div>
      <div class="params" data-testid="param-panel">
        <h2>参数</h2>
        <p v-if="!selectedNode" class="muted">点击节点选中后编辑参数</p>
        <template v-else>
          <h3>{{ typeMeta(selectedNode.type).label }} <span class="muted mono">{{ selectedNode.id }}</span></h3>
          <template v-if="selectedNode.type === 'change_source'">
            <label class="param-label">api_templates
              <textarea v-model="apiTemplatesText" rows="3" data-testid="param-api-templates" />
            </label>
            <label class="param-label">anchor_labels
              <textarea v-model="anchorLabelsText" rows="2" data-testid="param-anchor-labels" />
            </label>
          </template>
          <template v-else-if="selectedNode.type === 'replay_batch'">
            <label class="param-label">
              <input type="checkbox" v-model="confirmSideEffect" data-testid="param-confirm" />
              confirm_side_effect
            </label>
            <p class="warn-note">C1：勾选后真实执行副作用</p>
          </template>
          <p v-else class="muted">{{ typeMeta(selectedNode.type).desc }}</p>
          <div v-if="nodeArtifact(selectedNode.id)" class="artifact" data-testid="node-artifact">
            <h3>节点产物</h3>
            <pre class="code">{{ JSON.stringify(nodeArtifact(selectedNode.id), null, 2) }}</pre>
          </div>
        </template>
      </div>
    </div>
    <div v-if="runs.length" class="block">
      <h2>运行历史</h2>
      <table class="tbl">
        <thead><tr><th>id</th><th>状态</th><th>开始</th><th>结束</th><th>节点数</th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>#{{ r.id }}</td>
            <td><span class="dot" :class="'dot-'+r.status"></span>{{ r.status }}</td>
            <td>{{ r.started_at || "—" }}</td>
            <td>{{ r.finished_at || "—" }}</td>
            <td>{{ r.node_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.canvas-page { max-width: 1400px; }
.toolbar {
  display: flex; align-items: center; gap: 14px;
  margin-top: var(--space-4); font-size: 13px; flex-wrap: wrap;
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-lg); box-shadow: var(--shadow-sm);
  padding: var(--space-3) var(--space-4);
}
.toolbar label { display: flex; align-items: center; gap: 6px; }
.toolbar input { width: 180px; }
.run-hint { color: var(--color-success); font-size: 13px; font-weight: 500; }
.canvas-layout { display: flex; gap: var(--space-4); margin-top: var(--space-4); align-items: stretch; }
.palette { width: 200px; flex-shrink: 0; }
.palette h2, .params h2 {
  font-size: 14px; border-bottom: 1px solid var(--color-gray-3);
  padding-bottom: var(--space-1); margin-top: 0;
}
.palette-card {
  background: var(--color-surface); border: 1px solid var(--color-border);
  border-radius: var(--radius-md); box-shadow: var(--shadow-sm);
  padding: var(--space-2) var(--space-3); margin-bottom: var(--space-2);
  cursor: grab; display: flex; align-items: center; gap: 10px; transition: all 0.15s ease;
}
.palette-card:hover { border-color: var(--color-primary); transform: translateX(3px); box-shadow: var(--shadow-md); }
.palette-icon { font-size: 18px; width: 24px; text-align: center; }
.palette-text { display: flex; flex-direction: column; gap: 1px; }
.palette-label { font-weight: 600; font-size: 13px; }
.palette-desc { font-size: 11px; line-height: 1.3; }
.canvas-wrap {
  flex: 1; min-width: 0; height: 520px;
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md); overflow: hidden; background: var(--color-gray-1);
}
.vf-card {
  background: var(--color-surface); border: 2px solid var(--color-border);
  border-radius: 10px; min-width: 160px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  position: relative; cursor: pointer; transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.vf-card:hover { border-color: var(--color-primary); box-shadow: 0 4px 16px rgba(79,70,229,0.15); }
.vf-card.vf-selected { border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(79,70,229,0.15); }
.vf-card.vf-ok { border-color: var(--color-success); }
.vf-card.vf-error { border-color: var(--color-danger); }
.vf-header {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-radius: 8px 8px 0 0; border-bottom: 1px solid var(--color-gray-3);
}
.vf-icon { font-size: 14px; }
.vf-title { font-size: 13px; font-weight: 600; color: var(--color-gray-8); }
.vf-status-dot { width: 8px; height: 8px; border-radius: 50%; margin-left: auto; }
.vf-status-dot.ok { background: var(--color-success); }
.vf-body { padding: 6px 12px 8px; }
.vf-desc { font-size: 11px; line-height: 1.3; display: block; }
.vf-del {
  position: absolute; top: -8px; right: -8px; width: 20px; height: 20px;
  border-radius: 50%; background: var(--color-danger); color: white;
  font-size: 13px; font-weight: 700; border: 2px solid white; cursor: pointer;
  display: flex; align-items: center; justify-content: center; line-height: 1;
}
.params {
  width: 280px; flex-shrink: 0; background: var(--color-surface);
  border: 1px solid var(--color-border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm); padding: var(--space-3) var(--space-4);
}
.params h3 { font-size: 13px; margin: var(--space-3) 0 var(--space-2); display: flex; align-items: center; gap: 6px; }
.param-label { display: block; font-size: 12px; color: var(--color-gray-6); margin-bottom: 10px; }
.param-label textarea { width: 100%; margin-top: var(--space-1); font-size: 12px; font-family: var(--font-mono); }
.warn-note { color: var(--color-danger); font-size: 12px; margin: var(--space-1) 0 0; }
.artifact { margin-top: 14px; border-top: 1px solid var(--color-gray-3); padding-top: var(--space-2); }
.artifact h3 { margin: var(--space-2) 0 6px; }
.code { font-size: 12px; max-height: 260px; overflow-y: auto; }
</style>

<style>
@import "@vue-flow/core/dist/style.css";
@import "@vue-flow/core/dist/theme-default.css";
@import "@vue-flow/controls/dist/style.css";
@import "@vue-flow/minimap/dist/style.css";
.vue-flow__node { cursor: grab; }
.vue-flow__handle { width: 10px; height: 10px; background: #4f46e5; border: 2px solid white; }
.vue-flow__handle:hover { transform: scale(1.3); }
.vue-flow__edge-path { stroke-width: 2.5; }
.vue-flow__controls { box-shadow: 0 4px 12px rgba(0,0,0,0.12); border-radius: 8px; overflow: hidden; }
.vue-flow__minimap { border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.12); }
</style>