<script setup lang="ts">
// Task 3（S9 块C）：skill 详情——GET /skills/{id}/card 一次聚合，分区展示。
// 只读边界：不出现任何编辑入口。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  currentUser,
  exportSkillPlaywright,
  fetchVisualImage,
  getLocateProposals,
  getSkillCard,
  getSkillConsistency,
  getVisualBaseline,
  rejectLocateProposal,
  resetVisualBaseline,
} from "../api";
import type {
  AssertionRow,
  LocateProposalItem,
  SkillCard,
  SkillConsistency,
  VisualBaselineResponse,
} from "../api";

const route = useRoute();
const card = ref<SkillCard | null>(null);
const loading = ref(true);
const notFound = ref(false);
const error = ref("");
// S12 N4 层5：断言观测一致性（独立请求，失败/形状异常只藏行不炸页）
const consistency = ref<SkillConsistency | null>(null);
// S24 块 U：定位修复提案（自愈闭环；非关键路径失败静默藏区块）
const proposals = ref<LocateProposalItem[]>([]);
const proposalBusy = ref(false);
const canRejectProposal = computed(
  () => user?.role === "admin" || user?.role === "reviewer");

async function loadProposals(id: string): Promise<void> {
  try {
    proposals.value = await getLocateProposals(id);
  } catch {
    proposals.value = [];
  }
}

async function rejectProposal(pid: number): Promise<void> {
  proposalBusy.value = true;
  try {
    await rejectLocateProposal(pid);
    proposals.value = proposals.value.filter((p) => p.id !== pid
      || (p as { status?: string }).status !== "rejected");
    proposals.value = await getLocateProposals(String(route.params.id));
  } catch {
    /* 409 已否决等：刷新列表兜底 */
    proposals.value = await getLocateProposals(String(route.params.id));
  } finally {
    proposalBusy.value = false;
  }
}

// S22 块 T：视觉回归（基线/最新图并排 + 最近比对结果；非关键路径失败静默藏区块）
const visual = ref<VisualBaselineResponse | null>(null);
const visualBaselineUrl = ref("");
const visualLatestUrl = ref("");
const visualBusy = ref(false);
const visualMsg = ref("");
const user = currentUser();
const canResetVisual = computed(
  () => user?.role === "admin" || user?.role === "reviewer");

const diffPct = computed(() => {
  const ratio = visual.value?.last_result?.payload.diff_ratio;
  return ratio == null ? "—" : `${(ratio * 100).toFixed(2)}%`;
});

async function loadVisual(id: string): Promise<void> {
  try {
    visual.value = await getVisualBaseline(id);
    if (visual.value.baseline) {
      visualBaselineUrl.value = await fetchVisualImage(id, "baseline");
      // 最近比对存在才有 latest 图（建基线当次无比对）
      if (visual.value.last_result) {
        visualLatestUrl.value = await fetchVisualImage(id, "latest");
      }
    }
  } catch {
    visual.value = null; // 非关键路径：藏区块不炸页
  }
}

async function resetBaseline(): Promise<void> {
  visualBusy.value = true;
  visualMsg.value = "";
  try {
    await resetVisualBaseline(String(route.params.id));
    visualMsg.value = "已重置——下次 execute PASS 回放将重建基线";
    visual.value = await getVisualBaseline(String(route.params.id));
    visualBaselineUrl.value = "";
    visualLatestUrl.value = "";
  } catch (e) {
    visualMsg.value = e instanceof Error ? e.message : String(e);
  } finally {
    visualBusy.value = false;
  }
}

const confPct = computed(() =>
  card.value ? `${Math.round(card.value.confidence * 100)}%` : "");

/** 断言 payload 摘要：按 kind 提取人读期望。 */
function payloadSummary(a: AssertionRow): string {
  const p = a.payload || {};
  switch (a.kind) {
    case "api_status":
      return `${p.api_template} → ${p.expect_status}`;
    case "state_signal":
      return `${p.field}=${p.expect_value}（${p.api_template}）`;
    case "ui_text":
      return `${p.label}: ${p.before} → ${p.after}`;
    case "field_change":
      return `${p.field}: ${p.before} → ${p.after}（${p.api_template}）`;
    default:
      return JSON.stringify(p);
  }
}

/** 变量值列表：input_variables 每项 name + values 的采集值。 */
function varValues(values: Record<string, string> | undefined): string[] {
  return Object.values(values ?? {});
}

function fmtTime(ts: string): string {
  return ts.replace("T", " ").replace(/\.\d+.*$/, "");
}

onMounted(async () => {
  try {
    card.value = await getSkillCard(String(route.params.id));
  } catch (e) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      notFound.value = true;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
  // S12 N4 层5：一致性旁挂加载（非关键路径，失败静默藏行）
  getSkillConsistency(String(route.params.id))
    .then((c) => {
      if (typeof c?.consistent === "boolean") consistency.value = c;
    })
    .catch(() => {});
  loadVisual(String(route.params.id));
  loadProposals(String(route.params.id));
});
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <div v-else-if="notFound" class="empty">
      <span class="empty-icon">∅</span>
      <h1 class="empty-title">404</h1>
      <p class="empty-sub">Skill 不存在（可能已被 re-induce 重建，<RouterLink to="/skills">返回列表</RouterLink>）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card">
      <!-- 概要（S16 块 Q：卡片化） -->
      <header class="summary card">
        <h1>
          {{ card.name }}
          <span class="badge" :class="card.status === 'learned' ? 'badge-learned' : 'badge-candidate'">
            {{ card.status }}
          </span>
        </h1>
        <p class="desc">{{ card.description || "（无描述）" }}</p>
        <dl class="meta">
          <div><dt>置信度</dt><dd>{{ confPct }}（{{ card.confidence }}）</dd></div>
          <div><dt>证据数</dt><dd>{{ card.evidence_count }}</dd></div>
          <div><dt>断言数</dt><dd>{{ card.assertions.length }}</dd></div>
          <div v-if="consistency">
            <dt>一致性</dt>
            <dd data-testid="consistency">
              <span v-if="consistency.runs === 0" class="muted">暂无回放观测</span>
              <span v-else-if="consistency.consistent" class="ok">一致 ✓</span>
              <span v-else class="error">{{ consistency.inconsistent_count }} 项不一致</span>
            </dd>
          </div>
        </dl>
        <p v-if="card.superseded_by" class="notes superseded-hint">
          ⚠ 该版本已被 v{{ card.superseded_by }} 取代——回放/断言/验证请使用新版本（历史版本仅作审计）</p>
        <p v-if="card.notes" class="notes">备注：{{ card.notes }}</p>
      </header>

      <!-- 骨架步骤流 -->
      <div class="block">
        <h2>骨架步骤流</h2>
        <pre class="code"><code v-for="(step, i) in card.skeleton" :key="i">{{ i + 1 }}. {{ step.signature }}
</code></pre>
      </div>

      <!-- 变量 -->
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

      <!-- 断言表（S16 块 Q：kind 徽标列） -->
      <div class="block">
        <h2>断言（{{ card.assertions.length }}）</h2>
        <p v-if="card.assertions.length === 0" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>kind</th><th>layer</th><th>期望</th></tr></thead>
          <tbody>
            <tr v-for="a in card.assertions" :key="a.id">
              <td><span class="badge badge-kind">{{ a.kind }}</span></td>
              <td>L{{ a.layer }}</td>
              <td class="mono">{{ payloadSummary(a) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 窗口参数 -->
      <div class="block">
        <h2>窗口参数</h2>
        <p v-if="!card.window_params" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>参数</th><th>值</th></tr></thead>
          <tbody>
            <tr v-for="(v, k) in card.window_params" :key="String(k)">
              <td>{{ k }}</td><td class="mono">{{ v }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 最近 run -->
      <div class="block">
        <h2>最近回放</h2>
        <p v-if="!card.last_run" class="muted">未回放</p>
        <dl v-else class="meta">
          <div>
            <dt>状态</dt>
            <dd>
              <span class="dot" :class="`dot-${card.last_run.status}`"></span>{{ card.last_run.status }}
              <span v-if="card.last_run.flaky" class="badge badge-flaky" data-testid="flaky-badge">flaky</span>
            </dd>
          </div>
          <div><dt>模式</dt><dd>{{ card.last_run.mode }}</dd></div>
          <div><dt>时间</dt><dd>{{ fmtTime(card.last_run.ts) }}</dd></div>
        </dl>
      </div>

      <!-- S24 块 U：自愈提案（失败→归因→提案→验证链） -->
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
                <span v-if="p.applied_skill_id" class="muted">
                  → v#{{ p.applied_skill_id }}
                </span>
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

      <!-- S22 块 T：视觉回归 -->
      <div v-if="visual" class="block" data-testid="visual-section">
        <h2>视觉回归</h2>
        <p v-if="!visual.baseline" class="muted" data-testid="visual-empty">
          未建立视觉基线——首次 execute PASS 回放后自动建立
        </p>
        <template v-else>
          <dl class="meta">
            <div>
              <dt>最近比对</dt>
              <dd>
                <span v-if="visual.last_result"
                  class="dot"
                  :class="visual.last_result.passed ? 'dot-pass' : 'dot-fail'">
                </span>
                {{ visual.last_result ? (visual.last_result.passed ? "一致" : "视觉差异") : "未比对（基线刚建立）" }}
              </dd>
            </div>
            <div><dt>差异占比</dt><dd class="mono">{{ diffPct }}</dd></div>
            <div v-if="visual.last_result">
              <dt>哈希距离</dt>
              <dd class="mono">{{ visual.last_result.payload.hash_distance ?? "—" }}</dd>
            </div>
            <div v-if="visual.last_result?.payload.size_changed">
              <dt>尺寸变化</dt><dd>是（已按基线缩放比对）</dd>
            </div>
          </dl>
          <div class="visual-pair" data-testid="visual-pair">
            <figure>
              <img v-if="visualBaselineUrl" :src="visualBaselineUrl" alt="视觉基线截图" />
              <figcaption>基线（{{ fmtTime(visual.baseline.created_at) }}）</figcaption>
            </figure>
            <figure v-if="visualLatestUrl">
              <img :src="visualLatestUrl" alt="最近回放截图" />
              <figcaption>最近回放</figcaption>
            </figure>
          </div>
          <button
            v-if="canResetVisual"
            class="btn"
            :disabled="visualBusy"
            data-testid="visual-reset-btn"
            @click="resetBaseline"
          >
            {{ visualBusy ? "重置中…" : "重置基线" }}
          </button>
          <span v-if="visualMsg" class="muted">{{ visualMsg }}</span>
        </template>
      </div>

      <!-- 页脚：回放入口（Task 5，U1 缓解：详情页给"接下来做什么"的显式引导） -->
      <footer class="replay-cta">
        <RouterLink :to="`/replay/${card.id}`" class="replay-btn btn btn-primary">回放此 Skill</RouterLink>
        <button
          class="btn"
          data-testid="export-playwright-btn"
          @click="exportSkillPlaywright(card.id).catch(() => {})"
        >导出 Playwright 脚本</button>
        <span class="muted">触发 shadow/execute 回放并查看断言结果、前后快照对比。</span>
      </footer>
    </template>
  </section>
</template>

<style scoped>
/* S16 块 Q：颜色/表格/徽标/圆点/代码块走全局令牌类，这里只留布局差异 */
.summary {
  padding: var(--space-4) var(--space-6);
}
.summary h1 {
  margin: 0 0 var(--space-1);
  display: flex;
  align-items: center;
  gap: 10px;
}
.desc {
  color: var(--color-text-secondary);
  margin-top: 0;
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
.superseded-hint {
  color: var(--color-warning);
  font-weight: 600;
}
.notes {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.replay-cta {
  margin-top: var(--space-8);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-gray-3);
  display: flex;
  align-items: center;
  gap: var(--space-3);
}
.replay-btn {
  text-decoration: none;
}
/* 骨架步骤流：pre.code 内逐行 code 块 */
.code code {
  display: block;
}
/* S22 块 T：基线/最新截图并排 */
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
</style>
