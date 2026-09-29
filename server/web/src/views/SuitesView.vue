<script setup lang="ts">
// S37-3 测试套件：以套件为单位组织测试（操作流程组合 → 一键执行 → 汇总）。
//   - 套件列表（含操作流程概要）+ 新建（勾选操作流程）
//   - 一键执行：预演（默认，安全）/ 执行（勾选副作用确认，C1 门控）
//   - 执行汇总：X 个操作 / Y 通过 / 失败明细（链接 run 详情）
//   - 执行历史
import { onMounted, ref } from "vue";
import {
  createSuite,
  deleteSuite,
  listSuiteRuns,
  listSuites,
  runSuite,
} from "../api";
import type { SuiteItem, SuiteRunSummary } from "../api";
import { getSkills } from "../api";
import type { SkillListItem } from "../api";

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

function toggleSkill(id: number): void {
  if (checked.value.has(id)) checked.value.delete(id);
  else checked.value.add(id);
}

async function create(): Promise<void> {
  if (!newName.value.trim() || checked.value.size === 0) {
    createError.value = "请填写名称并勾选至少一个操作流程";
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createSuite(newName.value.trim(), [...checked.value]);
    newName.value = "";
    checked.value = new Set();
    await load();
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
  history.value = await listSuiteRuns(id);
}

async function remove(id: number): Promise<void> {
  await deleteSuite(id);
  await load();
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
    <h1>测试套件</h1>
    <p class="muted page-desc">
      以套件为单位组织测试：勾选操作流程组建套件，一键执行并汇总结果。
      预演模式只规划不执行（安全）；执行模式会真实操作目标系统（含写操作）。
    </p>

    <div class="block">
      <h2>新建套件</h2>
      <div class="create-row">
        <input
          v-model="newName"
          type="text"
          placeholder="套件名称（如：冒烟测试 / 回归套件）"
          aria-label="套件名称"
          data-testid="suite-name"
        />
        <button
          class="btn btn-primary"
          :disabled="creating"
          data-testid="suite-create"
          @click="create"
        >
          {{ creating ? "创建中…" : "创建套件" }}
        </button>
      </div>
      <p v-if="createError" class="error">{{ createError }}</p>
      <div class="skill-picker" data-testid="skill-picker">
        <label v-for="s in skills" :key="s.id" class="pick-row">
          <input
            type="checkbox"
            :checked="checked.has(s.id)"
            @change="toggleSkill(s.id)"
          />
          <span>{{ s.name }}</span>
          <span class="muted">（{{ s.status }} · 置信度 {{ Math.round(s.confidence * 100) }}%）</span>
        </label>
      </div>
    </div>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>
    <p v-else-if="suites.length === 0" class="muted">暂无套件，先在上方创建</p>

    <div v-for="s in suites" :key="s.id" class="block suite-card">
      <div class="suite-head">
        <h2>{{ s.name }}</h2>
        <span class="muted">{{ s.skills.length }} 个操作流程</span>
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
          <RouterLink :to="`/skills/${sk.id}`">{{ sk.name }}</RouterLink>
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
      <h2>执行汇总（{{ lastRun.total }} 个操作流程）</h2>
      <p class="run-line">
        <span class="ok">通过 {{ lastRun.pass_count }}</span> ·
        <span class="ng">失败 {{ lastRun.fail_count }}</span> ·
        <span class="skipped">异常 {{ lastRun.error_count }}</span> ·
        <span class="skipped">预演 {{ lastRun.shadow_count }}</span>
      </p>
      <table class="tbl">
        <thead><tr><th>操作流程</th><th>状态</th><th>模式</th><th>详情</th></tr></thead>
        <tbody>
          <tr v-for="r in lastRun.results" :key="r.run_id">
            <td>{{ r.skill_name }}</td>
            <td>
              <span class="dot" :class="`dot-${r.status}`"></span>{{ r.status }}
            </td>
            <td>{{ r.mode }}</td>
            <td><RouterLink :to="`/replay-runs/${r.run_id}`">run #{{ r.run_id }}</RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 执行历史 -->
    <div v-if="historySuiteId !== null" class="block" data-testid="suite-history">
      <h2>执行历史</h2>
      <table class="tbl">
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
