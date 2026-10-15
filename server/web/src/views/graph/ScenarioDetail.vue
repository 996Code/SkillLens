<script setup lang="ts">
// AQ1/AQ4 场景详情：步骤时间线（用户可读——技能 description 主文案+
// 技术名副标题+参数）+ 运行入口（executor.html 场景模式）+ 编辑模式
// （改名/启停步/换参/重排——PATCH /scenarios 带 If-Match 版本锁）。
// 技术下钻不断：步名链接技能详情（Katalon Manual/Script 双视图语义）。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getScenario, updateScenario, listScenarioRuns,
         listScenarioExpectations, bindScenarioExpectation,
         listConfirmedDeltas } from "../../api";
import type { ScenarioDetail, ScenarioRunRow,
              ScenarioExpectationRow, ConfirmedDeltaOption } from "../../api";
import { toastOk, toastErr } from "../../toast";
import { askConfirm } from "../../confirm";

const route = useRoute();
const scenario = ref<ScenarioDetail | null>(null);
const loading = ref(true);
const error = ref("");
const editing = ref(false);
const saving = ref(false);
const editName = ref("");

const EXT_EXECUTOR = "chrome-extension://iifhfcajmahbdbjljhmfknfnachpcpgl/executor.html";

const scenarioId = computed(() => String(route.params.scenarioId));

async function load(): Promise<void> {
  loading.value = true;
  try {
    scenario.value = await getScenario(scenarioId.value);
    editName.value = scenario.value.name;
    const sid = scenario.value.id;
    // 期望绑定与场景运行历史（新主链数据；失败不阻塞主视图）
    try { expectations.value = await listScenarioExpectations(sid); } catch { /* 期望 fail-open */ }
    try { deltaOptions.value = await listConfirmedDeltas(); } catch { /* 下拉 fail-open */ }
    try { runs.value = await listScenarioRuns(sid); } catch { /* 运行历史 fail-open */ }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

function startEdit(): void {
  if (!scenario.value) return;
  editing.value = true;
  editName.value = scenario.value.name;
}

async function save(): Promise<void> {
  if (!scenario.value) return;
  saving.value = true;
  try {
    const versionBeforeSave = scenario.value.definition_version;
    scenario.value = await updateScenario(scenario.value.id, versionBeforeSave, {
      name: editName.value.trim() || scenario.value.name,
      system: scenario.value.system,
      steps: scenario.value.steps.map((s) => ({
        skill_id: s.skill_id,
        scenario_id: s.scenario_id,
        overrides: s.overrides,
        enabled: s.enabled,
        setup: s.setup,
        row_anchor_from: s.row_anchor_from,
      })),
    });
    editing.value = false;
    toastOk("场景已保存");
  } catch (e) {
    toastErr(`保存失败：${e instanceof Error ? e.message : e}`);
    // 版本冲突时重载拿最新定义，避免继续编辑过期快照
    if (e instanceof Error && e.message.includes("409")) await load();
  } finally {
    saving.value = false;
  }
}

function toggleStep(i: number): void {
  const st = scenario.value?.steps[i];
  if (st) st.enabled = !st.enabled;
}

function moveStep(i: number, dir: -1 | 1): void {
  const steps = scenario.value?.steps;
  if (!steps) return;
  const j = i + dir;
  if (j < 0 || j >= steps.length) return;
  [steps[i], steps[j]] = [steps[j], steps[i]];
}

async function removeStep(i: number): Promise<void> {
  const steps = scenario.value?.steps;
  if (!steps || steps.length <= 1) {
    toastErr("场景至少保留一个步骤");
    return;
  }
  if (!(await askConfirm("确定移除该步骤？"))) return;
  steps.splice(i, 1);
}

function runScenario(): void {
  window.open(`${EXT_EXECUTOR}?scenario=${scenario.value!.id}&auto=1`, "_blank");
}

function overrideEntries(st: { overrides: Record<string, string> }): Array<[string, string]> {
  return Object.entries(st.overrides ?? {});
}

function setOverride(st: { overrides: Record<string, string> }, key: string, val: string): void {
  st.overrides[key] = val;
}

// ---------- AR 收尾：期望绑定 + 场景运行历史 ----------
const expectations = ref<ScenarioExpectationRow[]>([]);
const deltaOptions = ref<ConfirmedDeltaOption[]>([]);
const bindDeltaId = ref<number | "">("");
const runs = ref<ScenarioRunRow[]>([]);

const RUN_TONE: Record<string, string> = {
  pass: "badge-success", fail: "badge-fail", error: "badge-error",
  shadow: "badge-shadow", aborted: "badge-candidate",
  running: "badge-info", queued: "badge-info",
};

async function bindExpectation(): Promise<void> {
  if (!scenario.value || !bindDeltaId.value) return;
  try {
    await bindScenarioExpectation(scenario.value.id, Number(bindDeltaId.value), null);
    toastOk("期望已绑定——下次运行将自动生成对照报告");
    bindDeltaId.value = "";
    expectations.value = await listScenarioExpectations(scenario.value.id);
  } catch (e) {
    toastErr(`绑定失败：${e instanceof Error ? e.message : e}`);
  }
}

function fmtRunTime(ts: string | null): string {
  return ts ? ts.replace("T", " ").slice(0, 16) : "—";
}

onMounted(load);
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="scenario">
      <!-- 场景头 -->
      <div class="scenario-hero">
        <div class="scenario-hero-main">
          <h1 v-if="!editing">{{ scenario.name }}</h1>
          <input v-else v-model="editName" class="scenario-name-input"
                 aria-label="场景名称" data-testid="scenario-name-input" />
          <p class="muted page-desc">
            {{ scenario.system }} · {{ scenario.steps.length }} 步
            · 创建于 {{ scenario.created_at.slice(0, 10) }}
          </p>
        </div>
        <div class="scenario-hero-actions">
          <button v-if="!editing" class="btn btn-primary"
                  data-testid="scenario-run" @click="runScenario">
            ▶ 运行场景
          </button>
          <button v-if="!editing" class="btn btn-secondary"
                  data-testid="scenario-edit" @click="startEdit">
            编辑
          </button>
          <template v-else>
            <button class="btn btn-primary" :disabled="saving"
                    data-testid="scenario-save" @click="save">
              {{ saving ? "保存中…" : "保存" }}
            </button>
            <button class="btn btn-secondary" @click="editing = false; load()">
              取消
            </button>
          </template>
        </div>
      </div>

      <!-- 步骤时间线 -->
      <div class="block steps-block" data-testid="scenario-steps">
        <h2>步骤（{{ scenario.steps.length }}）</h2>
        <div class="step-timeline">
          <div v-for="(st, i) in scenario.steps" :key="i"
               class="step-node" :class="{ disabled: !st.enabled }"
               :data-testid="`scenario-step-${i}`">
            <div class="step-index">
              <span class="step-num">{{ i + 1 }}</span>
              <span v-if="st.setup" class="chip" title="前置步骤（登录等）">前置</span>
              <span v-if="st.row_anchor_from" class="chip"
                    title="行锚注入：沿用第 N 步选中的行">行锚←步{{ st.row_anchor_from }}</span>
            </div>
            <div class="step-body">
              <!-- 主文案：技能自然语言描述（95% 技能有 LLM 描述） -->
              <div class="step-desc">
                {{ st.skill?.description || st.skill?.name || (st.scenario_id ? `子场景 #${st.scenario_id}` : "（未知步骤）") }}
              </div>
              <!-- 副标题：技术名（下钻入口——双视图语义） -->
              <div class="step-tech">
                <template v-if="st.skill">
                  <RouterLink :to="`/graph/skill/${st.skill.id}`"
                              class="step-tech-link">
                    {{ st.skill.name }}
                  </RouterLink>
                  <span v-if="st.skill.requires_confirmation" class="badge badge-warning">
                    写操作
                  </span>
                </template>
              </div>
              <!-- 参数（换参） -->
              <div v-if="overrideEntries(st).length || (editing && st.skill?.fill_fields?.length)"
                   class="step-params">
                <div v-for="[k, v] in overrideEntries(st)" :key="k" class="param-row">
                  <span class="param-key mono">{{ k }}</span>
                  <span v-if="!editing" class="param-val mono">{{ v }}</span>
                  <input v-else class="param-input mono" :value="v"
                         :data-testid="`param-${i}-${k}`"
                         @input="setOverride(st, k, ($event.target as HTMLInputElement).value)" />
                </div>
                <div v-if="editing && st.skill?.fill_fields?.length"
                     class="param-candidates muted">
                  可用参数：
                  <span v-for="f in st.skill.fill_fields" :key="f.name"
                        class="chip chip-kind">{{ f.name }}</span>
                </div>
              </div>
            </div>
            <!-- 编辑操作 -->
            <div v-if="editing" class="step-ops">
              <button class="btn btn-sm" :title="st.enabled ? '禁用此步' : '启用此步'"
                      @click="toggleStep(i)">{{ st.enabled ? "禁用" : "启用" }}</button>
              <button class="btn btn-sm" title="上移" :disabled="i === 0"
                      @click="moveStep(i, -1)">↑</button>
              <button class="btn btn-sm" title="下移"
                      :disabled="i === scenario.steps.length - 1"
                      @click="moveStep(i, 1)">↓</button>
              <button class="btn btn-sm step-del" title="移除"
                      @click="removeStep(i)">×</button>
            </div>
          </div>
        </div>
      </div>
      <!-- 期望绑定（AR4：绑定期望后运行自动生成对照报告） -->
      <div class="block" data-testid="scenario-expectations">
        <h2>期望（{{ expectations.length }}）</h2>
        <p v-if="!expectations.length" class="muted">
          未绑定期望。绑定已确认的需求期望后，场景运行将自动生成四分类对照报告。
        </p>
        <table v-else class="tbl">
          <thead><tr><th>需求</th><th>期望</th><th>范围</th></tr></thead>
          <tbody>
            <tr v-for="e in expectations" :key="e.id">
              <td class="mono">{{ e.requirement_id }}</td>
              <td>#{{ e.expected_delta_id }}</td>
              <td>{{ e.step_index === null ? "场景级（全部业务步）" : `步骤 ${e.step_index + 1}` }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="deltaOptions.length" class="bind-row">
          <select v-model="bindDeltaId" aria-label="选择期望"
                  data-testid="expectation-select">
            <option value="">选择已确认的期望…</option>
            <option v-for="d in deltaOptions" :key="d.id" :value="d.id">
              {{ d.requirement_id }}（{{ d.change_count }} 项变更）
            </option>
          </select>
          <button class="btn btn-secondary" :disabled="!bindDeltaId"
                  data-testid="expectation-bind" @click="bindExpectation">
            绑定期望
          </button>
        </div>
      </div>

      <!-- 场景运行历史（AR2 真数据——替代链首 skill 近似） -->
      <div class="block" data-testid="scenario-run-history">
        <h2>运行历史（{{ runs.length }}）</h2>
        <p v-if="!runs.length" class="muted">尚未运行。点「运行场景」开始第一次执行。</p>
        <table v-else class="tbl">
          <thead><tr><th>#</th><th>状态</th><th>通过</th><th>执行端</th><th>时间</th></tr></thead>
          <tbody>
            <tr v-for="r in runs.slice(0, 10)" :key="r.id">
              <td>
                <RouterLink :to="`/graph/scenario-run/${r.id}`">#{{ r.id }}</RouterLink>
              </td>
              <td>
                <span class="badge" :class="RUN_TONE[r.status] || ''">{{ r.status }}</span>
              </td>
              <td>{{ r.pass_count }}/{{ r.total_count }}</td>
              <td class="muted">{{ r.executor }}</td>
              <td class="muted">{{ fmtRunTime(r.finished_at || r.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.bind-row {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
  align-items: center;
}
.bind-row select {
  max-width: 360px;
}
.scenario-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}
.scenario-hero-actions {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-2);
}
.scenario-name-input {
  font-size: 20px;
  font-weight: 700;
  width: 420px;
  max-width: 100%;
}
.steps-block {
  margin-top: var(--space-4);
}
.step-timeline {
  display: flex;
  flex-direction: column;
}
.step-node {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-4) 0;
  border-bottom: 1px solid var(--color-gray-2);
  position: relative;
}
.step-node:last-child {
  border-bottom: none;
}
.step-node.disabled {
  opacity: 0.45;
}
.step-node.disabled::after {
  content: "已禁用";
  position: absolute;
  right: var(--space-2);
  top: var(--space-2);
  font-size: 11px;
  color: var(--color-gray-5);
}
.step-index {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex: none;
  width: 40px;
}
.step-num {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 700;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.step-node.disabled .step-num {
  background: var(--color-gray-2);
  color: var(--color-gray-5);
}
.step-body {
  flex: 1;
  min-width: 0;
}
.step-desc {
  font-size: 14px;
  font-weight: 550;
  line-height: 1.5;
}
.step-tech {
  margin-top: 2px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
.step-tech-link {
  color: var(--color-gray-5);
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.step-tech-link:hover {
  color: var(--color-primary);
}
.step-params {
  margin-top: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.param-row {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  font-size: 12px;
}
.param-key {
  color: var(--color-gray-5);
  min-width: 140px;
}
.param-val {
  color: var(--color-primary);
}
.param-input {
  width: 260px;
  padding: 3px 8px;
  font-size: 12px;
}
.param-candidates {
  font-size: 11px;
  margin-top: 2px;
}
.step-ops {
  display: flex;
  gap: 4px;
  align-items: flex-start;
  flex: none;
}
.step-del:hover {
  color: var(--color-danger);
  border-color: var(--color-danger);
}
</style>
