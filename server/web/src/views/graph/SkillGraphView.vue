<script setup lang="ts">
// S39/S42 自动化流程图（图工作台内）：骨架+断言 → 节点图 + 详情面板。
// S42：SkillDetail 独有能力（断言表/变量/自愈提案/视觉回归/导出）并入——
// 单一流程详情页，旧 /skills/:id 视图废弃。
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  currentUser,
  exportSkillPlaywright,
  fetchVisualImage,
  getLocateProposals,
  getSkillCard,
  listSkillRuns,
  getSkillConsistency,
  getSkillFlow,
  getSkillStateMachine,
  getVisualBaseline,
  rejectLocateProposal,
  resetVisualBaseline,
} from "../../api";
import { toastOk, toastErr } from "../../toast";
import type {
  FlowGraphDTO,
  LocateProposalItem,
  SkillCard,
  SkillConsistency,
  StateMachineDTO,
  VisualBaselineResponse,
} from "../../api";
import type { SkillRunRow } from "../../api";
import { assertExpect } from "../../run-format";
import FlowGraph from "../../components/FlowGraph.vue";

const route = useRoute();
const card = ref<SkillCard | null>(null);
// UI 批2：run 历史（此前只有 last_run 一条——可追溯性对齐 TestRail）
const runsHistory = ref<SkillRunRow[]>([]);
const flow = ref<FlowGraphDTO | null>(null);
// S43-2：状态机归纳（多轮录制状态信号 → 转移图）
const stateMachine = ref<StateMachineDTO | null>(null);
const loading = ref(true);
const error = ref("");

// S12 N4 层5：断言观测一致性（非关键路径失败只藏行）
const consistency = ref<SkillConsistency | null>(null);
// S24 块 U：定位修复提案（自愈闭环）
const proposals = ref<LocateProposalItem[]>([]);
const proposalBusy = ref(false);
const user = currentUser();
const canRejectProposal = computed(
  () => user?.role === "admin" || user?.role === "reviewer");

// S22 块 T：视觉回归（基线/最新图并排）
const visual = ref<VisualBaselineResponse | null>(null);
const visualBaselineUrl = ref("");
const visualLatestUrl = ref("");
const visualBusy = ref(false);
const visualMsg = ref("");
const canResetVisual = computed(
  () => user?.role === "admin" || user?.role === "reviewer");

const diffPct = computed(() => {
  const ratio = visual.value?.last_result?.payload.diff_ratio;
  return ratio == null ? "—" : `${(ratio * 100).toFixed(2)}%`;
});

// 路由竞态守卫（评审）：快速切换左树流程时，旧流程的 side 数据
// （stateMachine/proposals/visual）晚到会覆盖新流程——seq 单调递增，
// 响应归来时非当前 seq 即丢弃
let sideSeq = 0;
async function loadSideData(id: string): Promise<void> {
  const seq = ++sideSeq;
  getSkillConsistency(id)
    .then((c) => {
      if (seq === sideSeq && typeof c?.consistent === "boolean") consistency.value = c;
    })
    .catch(() => {});
  getSkillStateMachine(id)
    .then((sm) => {
      if (seq === sideSeq && (sm?.nodes ?? []).length) stateMachine.value = sm;
    })
    .catch(() => {});
  try {
    const v = await getVisualBaseline(id);
    if (seq !== sideSeq) return;
    visual.value = v;
    if (v.baseline) {
      const b = await fetchVisualImage(id, "baseline");
      if (seq !== sideSeq) { URL.revokeObjectURL(b); return; }
      if (visualBaselineUrl.value) URL.revokeObjectURL(visualBaselineUrl.value);
      visualBaselineUrl.value = b;
      if (v.last_result) {
        const l = await fetchVisualImage(id, "latest");
        if (seq !== sideSeq) { URL.revokeObjectURL(l); return; }
        if (visualLatestUrl.value) URL.revokeObjectURL(visualLatestUrl.value);
        visualLatestUrl.value = l;
      }
    }
  } catch {
    if (seq === sideSeq) visual.value = null;
  }
  try {
    const p = await getLocateProposals(id);
    if (seq === sideSeq) proposals.value = p;
  } catch {
    if (seq === sideSeq) proposals.value = [];
  }
}

async function rejectProposal(pid: number): Promise<void> {
  proposalBusy.value = true;
  try {
    await rejectLocateProposal(pid);
  } catch {
    /* 409 已否决等：刷新列表兜底 */
  } finally {
    proposals.value = await getLocateProposals(String(route.params.skillId))
      .catch(() => []);
    proposalBusy.value = false;
  }
}

async function resetBaseline(): Promise<void> {
  visualBusy.value = true;
  visualMsg.value = "";
  try {
    await resetVisualBaseline(String(route.params.skillId));
    visualMsg.value = "已重置——下次 execute PASS 执行将重建基线";
    visual.value = await getVisualBaseline(String(route.params.skillId));
    visualBaselineUrl.value = "";
    visualLatestUrl.value = "";
  } catch (e) {
    visualMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    visualBusy.value = false;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  card.value = null;
  flow.value = null;
  consistency.value = null;
  proposals.value = [];
  stateMachine.value = null;
  visual.value = null;
  visualBaselineUrl.value = "";
  visualLatestUrl.value = "";
  try {
    const id = String(route.params.skillId);
    [card.value, flow.value] = await Promise.all([
      getSkillCard(id),
      getSkillFlow(id),
    ]);
    void loadSideData(id);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

// S41 修复：路由参数变化时重新加载（左树切换流程不刷新的根因）
watch(() => route.params.skillId, () => {
  if (route.name === "graph-skill") void load();
});

// blob URL 泄漏收口（评审）：组件卸载时释放视觉回归两图
onBeforeUnmount(() => {
  if (visualBaselineUrl.value) URL.revokeObjectURL(visualBaselineUrl.value);
  if (visualLatestUrl.value) URL.revokeObjectURL(visualLatestUrl.value);
  visualBaselineUrl.value = "";
  visualLatestUrl.value = "";
});

function varValues(values: Record<string, string> | undefined): string[] {
  return Object.values(values ?? {});
}

onMounted(() => {
  void load();
  void loadRuns();
});

async function loadRuns(): Promise<void> {
  try {
    runsHistory.value = await listSkillRuns(String(route.params.skillId));
  } catch {
    runsHistory.value = [];  // 历史区 fail-open（不阻塞主卡）
  }
}
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card && flow">
      <h1>
        {{ card.name }}
        <span class="badge" :class="card.status === 'learned' ? 'badge-learned' : 'badge-candidate'">
          {{ card.status }}
        </span>
      </h1>
      <p class="muted page-desc">
        {{ card.description }} · 置信度 {{ Math.round(card.confidence * 100) }}% ·
        证据 {{ card.evidence_count }} · 断言 {{ card.assertions.length }}
        <span v-if="consistency">
          · <span v-if="consistency.runs === 0">一致性：暂无执行观测</span>
          <span v-else-if="consistency.consistent" class="ok">一致性 ✓</span>
          <span v-else class="error">一致性：{{ consistency.inconsistent_count }} 项不一致</span>
        </span>
      </p>
      <p v-if="card.superseded_by" class="superseded-hint">
        ⚠ 该版本已被 v{{ card.superseded_by }} 取代——执行/断言/验证请使用新版本（历史版本仅作审计）
      </p>

      <!-- 流程图（骨架+断言节点） -->
      <div class="block" data-testid="skill-flow-block">
        <h2>流程图</h2>
        <p class="muted hint">
          页面 → 操作 → 断言 的节点链；点击节点查看签名与断言详情。
        </p>
        <FlowGraph :nodes="flow.nodes" :edges="flow.edges" />
      </div>

      <!-- S43-2 状态机归纳（多轮录制状态信号 → 转移图） -->
      <div v-if="stateMachine" class="block" data-testid="state-machine-block">
        <h2>状态机归纳</h2>
        <p class="muted hint">
          多轮录制的业务状态序列归纳：初始态
          <span v-for="s in stateMachine.initial" :key="s" class="chip chip-init">{{ s }}</span>
          → 转移（边计数）→ 终态
          <span v-for="s in stateMachine.final" :key="s" class="chip chip-final">{{ s }}</span>
        </p>
        <FlowGraph :nodes="stateMachine.nodes"
          :edges="stateMachine.edges.map((e) => ({ from: e.from, to: e.to }))" />
      </div>

      <!-- 断言表 -->
      <div class="block">
        <h2>断言（{{ card.assertions.length }}）</h2>
        <p v-if="card.assertions.length === 0" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>kind</th><th>layer</th><th>期望</th></tr></thead>
          <tbody>
            <tr v-for="a in card.assertions" :key="a.id">
              <td><span class="badge badge-kind">{{ a.kind }}</span></td>
              <td>L{{ a.layer }}</td>
              <td class="mono">{{ assertExpect(a) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 输入变量 -->
      <div class="block">
        <h2>输入变量</h2>
        <p v-if="card.input_variables.length === 0" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>变量</th><th>采集值</th></tr></thead>
          <tbody>
            <tr v-for="v in card.input_variables" :key="v.name">
              <td>{{ v.name }}</td>
              <td>
                <span v-for="(val, i) in varValues(v.values)" :key="i" class="chip">{{ val }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <template v-if="card.param_variables.length">
          <h3>API 参数变量</h3>
          <table class="tbl">
            <thead><tr><th>参数</th><th>采集值</th></tr></thead>
            <tbody>
              <tr v-for="p in card.param_variables" :key="String(p.param)">
                <td>{{ p.param }}</td>
                <td>
                  <span v-for="(val, i) in varValues(p.values)" :key="i" class="chip">{{ val }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>

      <!-- 自愈提案 -->
      <div v-if="proposals.length" class="block" data-testid="proposal-section">
        <h2>自愈提案</h2>
        <table class="tbl">
          <thead><tr><th>原标签</th><th>提案标签</th><th>状态</th><th>验证次数</th><th>源归因</th><th v-if="canRejectProposal"></th></tr></thead>
          <tbody>
            <tr v-for="p in proposals" :key="p.id">
              <td class="mono">{{ p.step_label }}</td>
              <td class="mono">{{ p.proposed_label }}</td>
              <td>
                <span class="badge" :class="`badge-${p.status}`">{{ p.status }}</span>
                <span v-if="p.applied_skill_id" class="muted">→ v#{{ p.applied_skill_id }}</span>
              </td>
              <td class="mono">{{ p.verify_count }}</td>
              <td class="attr-cell" :title="p.attribution ?? ''">
                {{ (p.attribution ?? "—").slice(0, 40) }}
              </td>
              <td v-if="canRejectProposal">
                <button
                  v-if="p.status !== 'rejected'"
                  class="btn btn-sm"
                  :disabled="proposalBusy"
                  :data-testid="`reject-${p.id}`"
                  @click="rejectProposal(p.id)"
                >否决</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 视觉回归 -->
      <div v-if="visual" class="block" data-testid="visual-section">
        <h2>视觉回归</h2>
        <p v-if="!visual.baseline" class="muted" data-testid="visual-empty">
          未建立视觉基线——首次 execute PASS 执行后自动建立
        </p>
        <template v-else>
          <dl class="meta">
            <div>
              <dt>最近比对</dt>
              <dd>
                <span v-if="visual.last_result" class="dot"
                  :class="visual.last_result.passed ? 'dot-pass' : 'dot-fail'"></span>
                {{ visual.last_result ? (visual.last_result.passed ? "一致" : "视觉差异") : "未比对（基线刚建立）" }}
              </dd>
            </div>
            <div><dt>差异占比</dt><dd class="mono">{{ diffPct }}</dd></div>
          </dl>
          <div class="visual-pair" data-testid="visual-pair">
            <figure>
              <img v-if="visualBaselineUrl" :src="visualBaselineUrl" alt="视觉基线截图" />
              <figcaption>基线</figcaption>
            </figure>
            <figure v-if="visualLatestUrl">
              <img :src="visualLatestUrl" alt="最近执行截图" />
              <figcaption>最近执行</figcaption>
            </figure>
          </div>
          <button v-if="canResetVisual" class="btn" :disabled="visualBusy"
            data-testid="visual-reset-btn" @click="resetBaseline">
            {{ visualBusy ? "重置中…" : "重置基线" }}
          </button>
          <span v-if="visualMsg" class="muted">{{ visualMsg }}</span>
        </template>
      </div>

      <!-- 执行历史（下钻到执行图）+ 操作入口 -->
      <div class="block" data-testid="skill-run-history">
        <h2>执行历史（{{ runsHistory.length }}）</h2>
        <p v-if="!runsHistory.length" class="muted">未执行</p>
        <table v-else class="tbl">
          <thead>
            <tr><th>Run</th><th>状态</th><th>模式</th><th>步数</th><th>失败类</th><th>耗时</th><th>时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in runsHistory.slice(0, 15)" :key="r.id">
              <td><RouterLink :to="`/graph/run/${r.id}`">#{{ r.id }}</RouterLink></td>
              <td>
                <span class="badge" :class="`badge-${r.status}`">
                  {{ r.status }}<template v-if="r.flaky"> ·flaky</template>
                </span>
              </td>
              <td class="muted">{{ r.mode }}</td>
              <td class="muted">{{ r.steps }}</td>
              <td class="muted">{{ r.failure_class ?? "—" }}</td>
              <td class="muted">{{ r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + "s" : "—" }}</td>
              <td class="muted">{{ r.created_at.replace("T", " ").slice(0, 16) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="replay-cta">
        <RouterLink :to="`/graph/replay/${card.id}`" class="replay-btn btn btn-primary">
          自动测试此流程
        </RouterLink>
        <button class="btn" data-testid="export-playwright-btn"
          @click="exportSkillPlaywright(card.id)
            .then(() => toastOk('Playwright 脚本已导出'))
            .catch((e) => toastErr(`导出失败：${e?.message ?? e}`))">
          导出 Playwright 脚本
        </button>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.hint {
  margin-top: 0;
  font-size: 12px;
}
.run-link {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 14px;
  text-decoration: none;
}
.superseded-hint {
  color: var(--color-warning);
  font-weight: 600;
}
.meta {
  margin: var(--space-2) 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-6);
}
.meta dt {
  font-size: 12px;
  color: var(--color-gray-5);
}
.meta dd {
  margin: 2px 0 0;
}
.visual-pair {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.visual-pair figure {
  margin: 0;
  max-width: 45%;
}
.visual-pair img {
  max-width: 100%;
  border: 1px solid var(--color-border, #ddd);
  border-radius: 6px;
}
.visual-pair figcaption {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}
.replay-cta {
  margin-top: var(--space-6);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-gray-3);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.replay-btn {
  text-decoration: none;
}
</style>
