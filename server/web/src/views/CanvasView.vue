<script setup lang="ts">
// S14 Task 3（块 H1）：编排画布——手写 SVG 画布（零新依赖）。
//   左：5 类型节点面板（点击添加，网格自动布局）
//   中：SVG 画布（节点=rect+text+端口圆点；端口点击连线；节点可拖动；选中删除）
//   右：选中节点参数表单（change_source 文本域 / replay_batch confirm 复选——
//       C1 默认不勾，勾选后真实执行副作用；其余类型只读说明）
//   运行后：节点按 node_outputs 段着色（有产物=绿描边；error_text 非空=红），
//   选中节点可下钻产物 JSON。
import { computed, onMounted, ref } from "vue";
import {
  getAgentRun,
  getCanvas,
  listCanvasRuns,
  listCanvases,
  runCanvas,
  saveCanvas,
} from "../api";
import type { AgentRunDetail, CanvasEdge, CanvasNode } from "../api";

// ---------- 节点类型元数据 ----------
interface NodeTypeMeta {
  type: string;
  label: string;
  desc: string;
}
const NODE_TYPES: NodeTypeMeta[] = [
  { type: "change_source", label: "变更集源",
    desc: "api_templates / anchor_labels 构造变更集" },
  { type: "impact_select", label: "Impact 选择", desc: "反查受影响 skill" },
  { type: "replay_batch", label: "批回放",
    desc: "受影响 skill 批量回放（默认 shadow）" },
  { type: "aggregate", label: "聚合", desc: "回放结果计数" },
  { type: "review_output", label: "评审输出", desc: "生成 markdown 摘要" },
];
function typeLabel(type: string): string {
  return NODE_TYPES.find((t) => t.type === type)?.label || type;
}

const NODE_W = 160;
const NODE_H = 60;

// ---------- 画布状态 ----------
const canvases = ref<{ id: number; name: string; created_at: string }[]>([]);
const canvasesLoading = ref(true);
const canvasesError = ref("");
const selectedCanvasId = ref(""); // '' = 新建
const currentCanvasId = ref<number | null>(null); // 已保存（可运行）的画布 id
const name = ref("");

const nodes = ref<CanvasNode[]>([]);
const edges = ref<CanvasEdge[]>([]);
let nodeSeq = 0;

const selectedNodeId = ref<string | null>(null);
const linkingFrom = ref<string | null>(null); // 连线态源节点 id
const svgEl = ref<SVGSVGElement | null>(null);

// ---------- 保存 / 运行 ----------
const saving = ref(false);
const saveError = ref("");
const savedHint = ref("");
const running = ref(false);
const runError = ref("");
const runHint = ref("");
const lastRun = ref<AgentRunDetail | null>(null);
const runs = ref<{ id: number; status: string; started_at: string | null;
  finished_at: string | null; node_count: number }[]>([]);

const selectedNode = computed<CanvasNode | null>(() =>
  nodes.value.find((n) => n.id === selectedNodeId.value) || null);

// change_source 参数：多行文本（逗号/换行分隔）↔ 数组
const apiTemplatesText = computed<string>({
  get: () =>
    ((selectedNode.value?.params.api_templates as string[]) || []).join("\n"),
  set: (v: string) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.api_templates =
      v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
  },
});
const anchorLabelsText = computed<string>({
  get: () =>
    ((selectedNode.value?.params.anchor_labels as string[]) || []).join("\n"),
  set: (v: string) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.anchor_labels =
      v.split(/[\n,]/).map((s) => s.trim()).filter(Boolean);
  },
});
// replay_batch：C1 confirm_side_effect 默认不勾（保存时定格，运行时不可临时改）
const confirmSideEffect = computed<boolean>({
  get: () => selectedNode.value?.params.confirm_side_effect === true,
  set: (v: boolean) => {
    if (!selectedNode.value) return;
    selectedNode.value.params.confirm_side_effect = v;
  },
});

// ---------- 画布操作 ----------
function addNode(type: string): void {
  nodeSeq += 1;
  const col = nodes.value.length % 5;
  const row = Math.floor(nodes.value.length / 5);
  nodes.value.push({
    id: `n${nodeSeq}`, type, params: {}, x: col * 200, y: row * 120,
  });
}

function onNodeClick(n: CanvasNode): void {
  if (linkingFrom.value && linkingFrom.value !== n.id) {
    // 连线态：点节点主体 → 创建边 A→B
    edges.value.push({ from: linkingFrom.value, to: n.id });
    linkingFrom.value = null;
    return;
  }
  selectedNodeId.value = n.id;
}

function onPortClick(n: CanvasNode): void {
  linkingFrom.value = linkingFrom.value === n.id ? null : n.id;
}

function onCanvasBlank(): void {
  linkingFrom.value = null; // 点空白取消连线
}

function removeNode(n: CanvasNode): void {
  nodes.value = nodes.value.filter((x) => x.id !== n.id);
  edges.value = edges.value.filter((e) => e.from !== n.id && e.to !== n.id);
  if (selectedNodeId.value === n.id) selectedNodeId.value = null;
  if (linkingFrom.value === n.id) linkingFrom.value = null;
}

// ---------- 拖动（jsdom 无真实拖拽，不做单测） ----------
let drag: { id: string; sx: number; sy: number; ox: number; oy: number } | null
  = null;
function onNodeMouseDown(n: CanvasNode, e: MouseEvent): void {
  const t = e.target as Element;
  if (t.closest('[data-testid="node-port"],[data-testid="node-delete"]')) return;
  drag = { id: n.id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y };
  window.addEventListener("mousemove", onDragMove);
  window.addEventListener("mouseup", onDragEnd);
}
function onDragMove(e: MouseEvent): void {
  if (!drag) return;
  const n = nodes.value.find((x) => x.id === drag!.id);
  if (!n) return;
  const rect = svgEl.value?.getBoundingClientRect();
  const scale = rect && rect.width > 0 ? 1000 / rect.width : 1;
  n.x = Math.max(0, drag.ox + (e.clientX - drag.sx) * scale);
  n.y = Math.max(0, drag.oy + (e.clientY - drag.sy) * scale);
}
function onDragEnd(): void {
  drag = null;
  window.removeEventListener("mousemove", onDragMove);
  window.removeEventListener("mouseup", onDragEnd);
}

// ---------- 着色与产物下钻 ----------
function nodeHasOutput(id: string): boolean {
  return (lastRun.value?.node_outputs || []).some((s) => s.node === id);
}
function nodeClass(id: string): Record<string, boolean> {
  const hasOut = nodeHasOutput(id);
  return {
    "node-selected": selectedNodeId.value === id,
    "node-ok": hasOut,
    "node-error": !!lastRun.value?.error_text && !hasOut,
  };
}
function nodeArtifact(n: CanvasNode):
  { node: string; output: Record<string, unknown> } | null {
  return (lastRun.value?.node_outputs || []).find((s) => s.node === n.id)
    || null;
}

// ---------- 边坐标（A 右缘中点 → B 左缘中点） ----------
function edgeCoords(e: CanvasEdge):
  { x1: number; y1: number; x2: number; y2: number } | null {
  const a = nodes.value.find((n) => n.id === e.from);
  const b = nodes.value.find((n) => n.id === e.to);
  if (!a || !b) return null;
  return {
    x1: a.x + NODE_W, y1: a.y + NODE_H / 2, x2: b.x, y2: b.y + NODE_H / 2,
  };
}

// ---------- 保存 / 运行 / 加载 ----------
function dagPayload(): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  return {
    nodes: nodes.value.map((n) => ({
      id: n.id, type: n.type, params: { ...n.params }, x: n.x, y: n.y })),
    edges: edges.value.map((e) => ({ from: e.from, to: e.to })),
  };
}

async function onSave(): Promise<void> {
  if (!name.value.trim()) {
    saveError.value = "请输入画布名称";
    return;
  }
  saving.value = true;
  saveError.value = "";
  savedHint.value = "";
  try {
    const saved = await saveCanvas(name.value.trim(), dagPayload());
    currentCanvasId.value = saved.id; // 版本化：新行
    selectedCanvasId.value = String(saved.id);
    savedHint.value = `已保存 #${saved.id}`;
    canvases.value = await listCanvases();
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e); // 422 detail
  } finally {
    saving.value = false;
  }
}

async function onRun(): Promise<void> {
  if (currentCanvasId.value == null) {
    runError.value = "请先保存画布再运行";
    return;
  }
  running.value = true;
  runError.value = "";
  runHint.value = "运行中…";
  lastRun.value = null;
  try {
    const resp = await runCanvas(currentCanvasId.value);
    lastRun.value = await getAgentRun(resp.id); // 详情端点：着色+产物下钻
    runHint.value = `运行完成：${lastRun.value.status}`;
    runs.value = await listCanvasRuns(currentCanvasId.value);
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e);
    runHint.value = "";
  } finally {
    running.value = false;
  }
}

async function onSelectCanvas(): Promise<void> {
  saveError.value = "";
  runError.value = "";
  runHint.value = "";
  savedHint.value = "";
  lastRun.value = null;
  runs.value = [];
  selectedNodeId.value = null;
  linkingFrom.value = null;
  if (!selectedCanvasId.value) { // 新建：清空画布
    name.value = "";
    nodes.value = [];
    edges.value = [];
    nodeSeq = 0;
    currentCanvasId.value = null;
    return;
  }
  try {
    const d = await getCanvas(selectedCanvasId.value);
    name.value = d.name;
    nodes.value = d.dag.nodes.map((n) => ({ ...n, params: { ...n.params } }));
    edges.value = d.dag.edges.map((e) => ({ ...e }));
    nodeSeq = nodes.value.length;
    currentCanvasId.value = d.id;
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  }
}

onMounted(async () => {
  try {
    canvases.value = await listCanvases();
  } catch (e) {
    canvasesError.value = e instanceof Error ? e.message : String(e);
  } finally {
    canvasesLoading.value = false;
  }
});
</script>

<template>
  <section>
    <h1>画布</h1>
    <p class="muted page-desc">
      节点式流水线编排：左侧添加节点 → 端口点击连线 → 右侧编辑参数 →
      保存/运行；运行后节点按产物着色，可下钻 JSON。
    </p>

    <!-- 顶部工具栏 -->
    <div class="toolbar" data-testid="canvas-toolbar">
      <label>
        画布
        <select v-model="selectedCanvasId" data-testid="canvas-select"
                @change="onSelectCanvas" aria-label="选择画布">
          <option value="">新建画布</option>
          <option v-for="c in canvases" :key="c.id" :value="String(c.id)">
            #{{ c.id }} {{ c.name }}
          </option>
        </select>
      </label>
      <label>
        名称
        <input v-model="name" type="text" placeholder="画布名称"
               data-testid="canvas-name" />
      </label>
      <button type="button" class="btn btn-secondary" data-testid="save-btn"
              :disabled="saving" @click="onSave">保存</button>
      <button type="button" class="btn btn-primary" data-testid="run-btn"
              :disabled="running" @click="onRun">运行</button>
      <span v-if="savedHint" class="muted">{{ savedHint }}</span>
      <span v-if="runHint" class="run-hint" data-testid="run-hint">{{ runHint }}</span>
    </div>
    <p v-if="canvasesLoading" class="muted">画布列表加载中…</p>
    <p v-else-if="canvasesError" class="error">画布列表加载失败：{{ canvasesError }}</p>
    <p v-if="saveError" class="error" data-testid="save-error">{{ saveError }}</p>
    <p v-if="runError" class="error" data-testid="run-error">{{ runError }}</p>

    <div class="canvas-layout">
      <!-- 左：节点面板 -->
      <div class="palette" data-testid="node-palette">
        <h2>节点</h2>
        <div v-for="t in NODE_TYPES" :key="t.type" class="palette-card card-hoverable"
             :data-testid="`palette-${t.type}`" @click="addNode(t.type)">
          <span class="palette-label">{{ t.label }}</span>
          <span class="muted palette-desc">{{ t.desc }}</span>
        </div>
      </div>

      <!-- 中：SVG 画布 -->
      <div class="canvas-wrap">
        <svg ref="svgEl" viewBox="0 0 1000 600" class="canvas-svg"
             data-testid="canvas-svg" @click.self="onCanvasBlank">
          <defs>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="7"
                    refY="4" orient="auto">
              <path d="M0,0 L8,4 L0,8 z" class="edge-arrow" />
            </marker>
          </defs>
          <line v-for="(e, i) in edges" :key="i" v-bind="edgeCoords(e) || {}"
                class="edge" data-testid="canvas-edge" marker-end="url(#arrow)" />
          <g v-for="n in nodes" :key="n.id" class="cnode"
             :class="nodeClass(n.id)" :transform="`translate(${n.x},${n.y})`"
             data-testid="canvas-node" :data-id="n.id"
             @click="onNodeClick(n)" @mousedown="onNodeMouseDown(n, $event)">
            <rect class="node-rect" :width="NODE_W" :height="NODE_H" rx="6" />
            <text class="node-text" :x="NODE_W / 2" :y="NODE_H / 2 + 5">
              {{ typeLabel(n.type) }}
            </text>
            <circle class="port" :class="{ 'port-active': linkingFrom === n.id }"
                    :cx="NODE_W" :cy="NODE_H / 2" r="6" data-testid="node-port"
                    :data-id="n.id" @click.stop="onPortClick(n)" />
            <text v-if="selectedNodeId === n.id" class="node-del" :x="NODE_W - 12"
                  y="18" data-testid="node-delete" @click.stop="removeNode(n)">×</text>
          </g>
          <text v-if="nodes.length === 0" class="empty-hint" x="500" y="300">
            画布为空，点击左侧节点类型添加
          </text>
        </svg>
      </div>

      <!-- 右：参数表单 -->
      <div class="params" data-testid="param-panel">
        <h2>参数</h2>
        <p v-if="!selectedNode" class="muted">点击画布节点选中后编辑参数</p>
        <template v-else>
          <h3>{{ typeLabel(selectedNode.type) }}
            <span class="muted mono">{{ selectedNode.id }}</span>
          </h3>
          <template v-if="selectedNode.type === 'change_source'">
            <label class="param-label">
              api_templates（逗号/换行分隔）
              <textarea v-model="apiTemplatesText" rows="3"
                        data-testid="param-api-templates" />
            </label>
            <label class="param-label">
              anchor_labels（逗号/换行分隔）
              <textarea v-model="anchorLabelsText" rows="2"
                        data-testid="param-anchor-labels" />
            </label>
          </template>
          <template v-else-if="selectedNode.type === 'replay_batch'">
            <label class="param-label">
              <input type="checkbox" v-model="confirmSideEffect"
                     data-testid="param-confirm" />
              confirm_side_effect
            </label>
            <p class="warn-note">C1：勾选后真实执行副作用</p>
          </template>
          <p v-else class="muted">
            {{ NODE_TYPES.find((t) => t.type === selectedNode!.type)?.desc }}
            （该类型无参数）
          </p>

          <!-- 产物下钻：运行后选中节点显示该段 JSON -->
          <div v-if="nodeArtifact(selectedNode)" class="artifact"
               data-testid="node-artifact">
            <h3>节点产物</h3>
            <pre class="code">{{ JSON.stringify(nodeArtifact(selectedNode), null, 2) }}</pre>
          </div>
        </template>
      </div>
    </div>

    <!-- 运行历史 -->
    <div v-if="runs.length" class="block">
      <h2>运行历史</h2>
      <table class="tbl">
        <thead><tr><th>id</th><th>状态</th><th>开始</th><th>结束</th><th>节点数</th></tr></thead>
        <tbody>
          <tr v-for="r in runs" :key="r.id">
            <td>#{{ r.id }}</td>
            <td>{{ r.status }}</td>
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
/* S16 块 Q：按钮/表格/代码块/分区块卡片走全局令牌类，这里只留画布布局与 SVG 着色 */
.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: var(--space-4);
  font-size: 13px;
  flex-wrap: wrap;
}
.toolbar label {
  display: flex;
  align-items: center;
  gap: 6px;
}
.toolbar input {
  width: 180px;
}
.run-hint {
  color: var(--color-success);
  font-size: 13px;
}
.canvas-layout {
  display: flex;
  gap: var(--space-4);
  margin-top: var(--space-4);
  align-items: flex-start;
}
.palette {
  width: 190px;
  flex-shrink: 0;
}
.palette h2,
.params h2 {
  font-size: 14px;
  border-bottom: 1px solid var(--color-gray-3);
  padding-bottom: var(--space-1);
  margin-top: 0;
}
.palette-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  padding: var(--space-2) var(--space-3);
  margin-bottom: var(--space-2);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.palette-card:hover {
  background: var(--color-primary-soft);
  border-color: var(--color-primary-border);
}
.palette-label {
  font-weight: 600;
  font-size: 13px;
}
.palette-desc {
  font-size: 12px;
}
.canvas-wrap {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  background: var(--color-surface);
}
.canvas-svg {
  width: 100%;
  height: auto;
  display: block;
  background: var(--color-gray-1);
}
.edge {
  stroke: var(--color-gray-6);
  stroke-width: 2;
}
.edge-arrow {
  fill: var(--color-gray-6);
}
.cnode {
  cursor: pointer;
}
.cnode .node-rect {
  fill: var(--color-surface);
  stroke: var(--color-primary);
  stroke-width: 1.5;
}
.cnode.node-selected .node-rect {
  stroke-width: 3;
}
.cnode.node-ok .node-rect {
  stroke: var(--color-success);
  stroke-width: 3;
}
.cnode.node-error .node-rect {
  stroke: var(--color-danger);
  stroke-width: 3;
}
.node-text {
  font-size: 13px;
  text-anchor: middle;
  fill: var(--color-gray-7);
  user-select: none;
}
.port {
  fill: var(--color-primary);
  cursor: crosshair;
}
.port-active {
  fill: var(--color-warning);
  r: 8;
}
.node-del {
  font-size: 16px;
  fill: var(--color-danger);
  cursor: pointer;
  user-select: none;
}
.empty-hint {
  font-size: 14px;
  fill: var(--color-gray-5);
  text-anchor: middle;
}
.params {
  width: 260px;
  flex-shrink: 0;
}
.params h3 {
  font-size: 13px;
  margin: var(--space-3) 0 var(--space-2);
}
.param-label {
  display: block;
  font-size: 12px;
  color: var(--color-gray-6);
  margin-bottom: 10px;
}
.param-label textarea {
  width: 100%;
  margin-top: var(--space-1);
  font-size: 12px;
  font-family: var(--font-mono);
}
.warn-note {
  color: var(--color-danger);
  font-size: 12px;
  margin: var(--space-1) 0 0;
}
.artifact {
  margin-top: 14px;
}
.artifact h3 {
  margin: var(--space-2) 0 6px;
}
/* 产物 JSON：覆盖全局 .code 限高 */
.code {
  font-size: 12px;
  max-height: 260px;
  overflow-y: auto;
}
</style>
