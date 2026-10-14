<script setup lang="ts">
// S37-3 流程分组：以分组为单位组织测试（自动化流程组合 → 一键执行 → 汇总）。
//   - 分组列表（含自动化流程概要）+ 新建（勾选自动化流程）
//   - 一键执行：预演（默认，安全）/ 执行（勾选副作用确认，C1 门控）
//   - 执行汇总：X 个操作 / Y 通过 / 失败明细（链接 run 详情）
//   - 执行历史
import { computed, onMounted, ref } from "vue";

// S42：分组增删后通知壳刷新左树计数（此前 graph-changed 是死接线）
const emit = defineEmits<{ graphChanged: [] }>();
import {
  createSuite,
  deleteSuite,
  listSuiteRuns,
  listSuites,
  runSuite,
} from "../api";
import { askConfirm } from "../confirm";
import type { SuiteItem, SuiteRunSummary } from "../api";
import { getSkills } from "../api";
import type { SkillListItem } from "../api";
import { groupBySystem } from "../system-group";

const suites = ref<SuiteItem[]>([]);
const skills = ref<SkillListItem[]>([]);
const loading = ref(true);
const error = ref("");

// ---------- 新建 ----------
const newName = ref("");
const checked = ref<Set<number>>(new Set());
const creating = ref(false);
const createError = ref("");

// ---------- 执行 ----------
const runningId = ref<number | null>(null);
const confirmSideEffect = ref(false);
const lastRun = ref<SuiteRunSummary | null>(null);
const runError = ref("");

// ---------- 历史 ----------
const historySuiteId = ref<number | null>(null);
const history = ref<SuiteRunSummary[]>([]);
const historyLoading = ref(false);
const historyError = ref("");

function toggleSkill(id: number): void {
  if (checked.value.has(id)) checked.value.delete(id);
  else checked.value.add(id);
}

// UI 批2：选择器重构——249 平铺 checkbox → 系统分组 + 搜索 + 已选 chips
const pickerQuery = ref("");
const pickerGroups = computed(() => {
  const q = pickerQuery.value.trim().toLowerCase();
  const pool = q
    ? skills.value.filter((s) => s.name.toLowerCase().includes(q)
                           || (s.system ?? "").toLowerCase().includes(q))
    : skills.value;
  return groupBySystem(pool);
});
const checkedSkills = computed(() =>
  skills.value.filter((s) => checked.value.has(s.id)));
function toggleGroup(sys: string, ids: number[]): void {
  const all = ids.every((i) => checked.value.has(i));
  for (const i of ids) {
    if (all) checked.value.delete(i);
    else checked.value.add(i);
  }
}

async function create(): Promise<void> {
  if (!newName.value.trim() || checked.value.size === 0) {
    createError.value = "请填写名称并勾选至少一个自动化流程";
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createSuite(newName.value.trim(), [...checked.value]);
    newName.value = "";
    checked.value = new Set();
    await load();
    emit("graph-changed");
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

async function run(id: number): Promise<void> {
  runningId.value = id;
  runError.value = "";
  lastRun.value = null;
  try {
    lastRun.value = await runSuite(id, confirmSideEffect.value);
    historySuiteId.value = null;
  } catch (e) {
    runError.value = e instanceof Error ? e.message : String(e);
  } finally {
    runningId.value = null;
  }
}

async function showHistory(id: number): Promise<void> {
  if (historySuiteId.value === id) {
    historySuiteId.value = null;
    return;
  }
  historySuiteId.value = id;
  history.value = []; // 换套件先清旧数据，防上一套件的历史残留
  historyError.value = "";
  historyLoading.value = true;
  try {
    history.value = await listSuiteRuns(id);
  } catch (e) {
    history.value = [];
    historyError.value = e instanceof Error ? e.message : String(e);
  } finally {
    historyLoading.value = false;
  }
}

async function remove(id: number): Promise<void> {
  if (!(await askConfirm("确定删除该分组？（不可恢复，执行历史保留）"))) return;
  try {
    await deleteSuite(id);
    await load();
    emit("graph-changed");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    [suites.value, skills.value] = await Promise.all([listSuites(), getSkills()]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(() => void load());
</script>

<template>
  <section>
    <h1>流程分组</h1>
    <p class="muted page-desc">
      以分组为单位组织测试：勾选自动化流程组建分组，一键执行并汇总结果。
      预演模式只规划不执行（安全）；执行模式会真实操作目标系统（含写操作）。
    </p>

    <div class="block">
      <h2>新建分组</h2>
      <div class="create-row">
        <input
          v-model="newName"
          type="text"
          placeholder="分组名称（如：冒烟测试 / 回归集）"
          aria-label="分组名称"
          data-testid="suite-name"
        />
        <button
          class="btn btn-primary"
          :disabled="creating"
          data-testid="suite-create"
          @click="create"
        >
          {{ creating ? "创建中…" : "创建分组" }}
        </button>
      </div>
      <p v-if="createError" class="error">{{ createError }}</p>
      <div v-if="checkedSkills.length" class="picked-chips" data-testid="picked-chips">
        <span v-for="s in checkedSkills" :key="s.id" class="chip picked-chip">
          {{ s.name }}
          <button class="chip-x" type="button"
                  :aria-label="`移除 ${s.name}`" @click="toggleSkill(s.id)">×</button>
        </span>
      </div>
      <input
        v-model="pickerQuery"
        type="text"
        class="picker-search"
        placeholder="搜索流程名/系统…"
        aria-label="搜索流程"
        data-testid="picker-search"
      />
      <div class="skill-picker" data-testid="skill-picker">
        <div v-for="[sys, list] in pickerGroups" :key="sys" class="pick-group">
          <div class="pick-group-head">
            <button class="btn btn-sm" type="button"
                    @click="toggleGroup(sys, list.map((s) => s.id))">
              全选/清空
            </button>
            <span class="pick-group-name">{{ sys }}</span>
            <span class="muted">{{ list.length }}</span>
          </div>
          <label v-for="s in list" :key="s.id" class="pick-row">
            <input
              type="checkbox"
              :checked="checked.has(s.id)"
              @change="toggleSkill(s.id)"
            />
            <span>{{ s.name }}</span>
            <span class="muted">（{{ s.status }} · 置信度 {{ Math.round(s.confidence * 100) }}%）</span>
          </label>
        </div>
        <p v-if="!pickerGroups.length" class="muted">无匹配流程</p>
      </div>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <p v-else-if="suites.length === 0" class="muted">暂无分组，先在上方创建</p>

    <div v-for="s in suites" :key="s.id" class="block suite-card">
      <div class="suite-head">
        <h2>{{ s.name }}</h2>
        <span class="muted">{{ s.skills.length }} 个自动化流程</span>
        <button
          class="btn btn-primary"
          :disabled="runningId !== null"
          :data-testid="`suite-run-${s.id}`"
          @click="run(s.id)"
        >
          {{ runningId === s.id ? "执行中…" : "一键执行" }}
        </button>
        <button class="btn btn-secondary" @click="showHistory(s.id)">
          执行历史
        </button>
        <button class="btn btn-danger" @click="remove(s.id)">删除</button>
      </div>
      <ul class="suite-skills">
        <li v-for="sk in s.skills" :key="sk.id">
          <RouterLink :to="`/graph/skill/${sk.id}`">{{ sk.name }}</RouterLink>
        </li>
      </ul>
    </div>

    <!-- C1 门控 + 执行汇总 -->
    <label class="confirm-box">
      <input v-model="confirmSideEffect" type="checkbox" data-testid="suite-confirm" />
      执行模式（真实操作系统，含写操作副作用）；不勾选 = 预演（只规划不执行）
    </label>
    <p v-if="runError" class="error">{{ runError }}</p>

    <div v-if="lastRun" class="block" data-testid="suite-run-summary">
      <h2>执行汇总（{{ lastRun.total }} 个自动化流程）</h2>
      <p class="run-line">
        <span class="ok">通过 {{ lastRun.pass_count }}</span> ·
        <span class="ng">失败 {{ lastRun.fail_count }}</span> ·
        <span class="skipped">异常 {{ lastRun.error_count }}</span> ·
        <span class="skipped">预演 {{ lastRun.shadow_count }}</span>
      </p>
      <table class="tbl">
        <thead><tr><th>自动化流程</th><th>状态</th><th>模式</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-for="r in lastRun.results" :key="r.run_id">
            <td>{{ r.skill_name }}</td>
            <td>
              <span class="dot" :class="`dot-${r.status}`"></span>{{ r.status }}
            </td>
            <td>{{ r.mode }}</td>
            <td><RouterLink :to="`/graph/run/${r.run_id}`">run #{{ r.run_id }}</RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 执行历史 -->
    <div v-if="historySuiteId !== null" class="block" data-testid="suite-history">
      <h2>执行历史</h2>
      <p v-if="historyLoading" class="muted">加载中…</p>
      <p v-else-if="historyError" class="error" data-testid="history-error">
        加载失败：{{ historyError }}
      </p>
      <table v-else class="tbl">
        <thead><tr><th>#</th><th>汇总</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="h in history" :key="h.id">
            <td>#{{ h.id }}</td>
            <td>
              通过 {{ h.pass_count }} / 失败 {{ h.fail_count }} /
              异常 {{ h.error_count }} / 预演 {{ h.shadow_count }}
            </td>
            <td>{{ h.created_at.replace("T", " ").slice(0, 16) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.create-row {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.create-row input {
  flex: 1;
  max-width: 360px;
}
.skill-picker {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--space-1) var(--space-3);
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid var(--color-gray-3);
  border-radius: var(--radius-md);
  padding: var(--space-2);
}
.pick-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.suite-head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.suite-head h2 {
  margin: 0;
  border-bottom: none;
}
.suite-skills {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  font-size: 13px;
}
.confirm-box {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-warning-border);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  font-size: 13px;
  color: var(--color-warning);
  max-width: 560px;
}
.run-line {
  font-size: 15px;
}
.ok { color: var(--color-success); }
.ng { color: var(--color-danger); font-weight: 700; }
.skipped { color: var(--color-gray-5); }
</style>

/* UI 批2：选择器重构 */
.picked-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: var(--space-2);
}
.picked-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--color-primary-soft, #e0e7ff);
}
.chip-x {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  color: var(--color-gray-6);
  padding: 0 2px;
}
.chip-x:hover { color: var(--color-danger, #dc2626); }
.picker-search {
  width: 100%;
  margin-bottom: var(--space-2);
  padding: 6px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}
.pick-group {
  margin-bottom: var(--space-2);
}
.pick-group-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  position: sticky;
  top: 0;
  background: var(--color-surface);
  padding: 2px 0;
}
.pick-group-name {
  font-weight: 700;
  font-size: 13px;
}
