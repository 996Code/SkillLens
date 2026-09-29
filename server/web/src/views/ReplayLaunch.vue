<script setup lang="ts">
// Task 5（S9 块C C3+C1 UI）：自动测试触发与结果。
// 提交走 POST /expected-deltas/{id}/observe（同步返回，无需轮询）；
// observe 的 replay 概要在响应里，断言明细/快照再取 GET /replay-runs/{id}。
// C1 门控：模式单选 shadow（默认）/execute + "我已确认副作用"复选，
// execute 时二者不齐禁用提交（二要素齐备才发 confirm_side_effect=true）。
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { getReplayRun, getSkillCard, replayObserve } from "../api";
import type { ReplayRunDetail, SkillCard } from "../api";
import { assertExpect, assertObserved, snapshotDiffRows } from "../run-format";

const route = useRoute();

const card = ref<SkillCard | null>(null);
const loading = ref(true);
const notFound = ref(false);
const error = ref("");

// ---------- 表单状态 ----------
const mode = ref<"shadow" | "execute">("shadow");
const confirmed = ref(false);
const deltaId = ref("");
const overrides = reactive<Record<string, string>>({});

// ---------- 结果状态 ----------
const submitting = ref(false);
const observeError = ref(""); // 409 等业务拒绝（含 shadow 未执行）
const observeErrorStatus = ref(0);
const runId = ref<number | null>(null);
const replayStatus = ref("");
const runDetail = ref<ReplayRunDetail | null>(null);

/** C1 门控：shadow 天然安全可直接提交；execute 必须勾副作用复选。 */
const canSubmit = computed(() => {
  if (submitting.value) return false;
  if (mode.value === "shadow") return true;
  return confirmed.value;
});

/** 快照对比行：label + before → after，只保留有差异的行（前 10 行）。 */
const snapshotDiff = computed(() => snapshotDiffRows(runDetail.value?.plan ?? null));

/** 提交用的 overrides：剔除空值——空 = 沿用录制采集值
 * （后端 overrides.get(name, original) 对空串不会回退，须前端剔除）。 */
function overridesToSend(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(overrides)) {
    if (v.trim() !== "") out[k] = v;
  }
  return out;
}

async function submit() {
  if (!canSubmit.value) return;
  const id = deltaId.value.trim();
  if (!id || !/^\d+$/.test(id)) {
    observeError.value = "请输入有效的 expected_delta id（数字）";
    observeErrorStatus.value = 0;
    return;
  }
  submitting.value = true;
  observeError.value = "";
  observeErrorStatus.value = 0;
  runId.value = null;
  replayStatus.value = "";
  runDetail.value = null;
  try {
    const resp = await replayObserve(id, {
      skill_id: card.value!.id,
      overrides: overridesToSend(),
      confirm_side_effect: mode.value === "execute" && confirmed.value,
    });
    runId.value = resp.replay_run_id;
    replayStatus.value = resp.replay_status;
    // 断言明细/快照在 run 上，补一次读取；失败不阻塞状态展示
    try {
      runDetail.value = await getReplayRun(resp.replay_run_id);
    } catch {
      /* run 读取失败仅缺明细区 */
    }
  } catch (e) {
    observeErrorStatus.value =
      e instanceof Error && "status" in e ? (e as { status: number }).status : 0;
    observeError.value = e instanceof Error ? e.message : String(e);
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  try {
    card.value = await getSkillCard(String(route.params.skillId));
    for (const v of card.value.input_variables) {
      overrides[v.name] = ""; // 默认空 = 用录制时采集值
    }
  } catch (e) {
    if (e instanceof Error && "status" in e && (e as { status: number }).status === 404) {
      notFound.value = true;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <div v-else-if="notFound" class="empty">
      <span class="empty-icon">∅</span>
      <h1 class="empty-title">404</h1>
      <p class="empty-sub">Skill 不存在（<RouterLink to="/graph">返回列表</RouterLink>）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card">
      <header>
        <h1>自动测试 · 操作流程 #{{ card.id }}：{{ card.name }}</h1>
        <p class="muted">
          通过目标 delta 执行自动测试观测（observe）：server 会真实执行回放，
          结果与 delta 观测一并落库。
        </p>
      </header>

      <form class="launch" @submit.prevent="submit">
        <!-- overrides：从 card.input_variables 动态生成 -->
        <div class="block">
          <h2>参数覆盖（overrides）</h2>
          <p class="muted hint">
            留空表示沿用录制时采集的值；填写则回放时覆盖该变量。
          </p>
          <p v-if="card.input_variables.length === 0" class="muted">无输入变量</p>
          <div v-else class="override-list">
            <label v-for="v in card.input_variables" :key="v.name" class="override-row">
              <span class="ov-name">{{ v.name }}</span>
              <input v-model="overrides[v.name]" type="text" :placeholder="`覆盖 ${v.name}（留空用录制值）`" />
            </label>
          </div>
        </div>

        <!-- C1：模式单选 + 副作用确认复选 -->
        <div class="block">
          <h2>模式</h2>
          <div class="modes">
            <label class="mode">
              <input v-model="mode" type="radio" value="shadow" />
              <span><strong>预演</strong>（默认）——只规划不执行，安全核验</span>
            </label>
            <label class="mode">
              <input v-model="mode" type="radio" value="execute" />
              <span><strong>执行</strong>——真实操作系统（含写操作副作用）</span>
            </label>
          </div>
          <label v-if="mode === 'execute'" class="confirm-box">
            <input v-model="confirmed" type="checkbox" />
            <span>我已确认此操作有副作用，并在旁观察执行过程</span>
          </label>
        </div>

        <!-- 目标 delta -->
        <div class="block">
          <h2>目标 delta</h2>
          <p class="muted hint">
            填写已确认（confirmed）的 expected_delta id。提交走
            POST /expected-deltas/{id}/observe——shadow 回放不产生观测会被 409 拒绝，
            需要观测数据请选 execute；未确认的 delta 同样 409。
          </p>
          <input v-model="deltaId" type="text" inputmode="numeric"
                 placeholder="expected_delta_id" aria-label="expected_delta_id" />
        </div>

        <button type="submit" class="btn btn-primary" :disabled="!canSubmit">
          {{ submitting ? "测试中…（回放在常驻浏览器窗口执行，完成后此处显示结果）" : "执行自动测试" }}
        </button>
        <p v-if="mode === 'execute' && !confirmed" class="muted gate-hint">
          勾选副作用确认后才能提交（C1 安全门控）。
        </p>
      </form>

      <!-- 409 等业务拒绝：友好展示 -->
      <div v-if="observeError" class="reject" :class="{ 'reject-409': observeErrorStatus === 409 }">
        <h3>{{ observeErrorStatus === 409 ? "测试未执行（安全拒绝）" : `请求失败${observeErrorStatus ? `（${observeErrorStatus}）` : ""}` }}</h3>
        <p class="mono">{{ observeError }}</p>
        <p v-if="observeErrorStatus === 409" class="muted">
          这是预期内的安全行为：observe 需要 execute 模式（勾选副作用确认）才会真实执行；
          "shadow run 未执行，无观测"即 shadow 计划被安全拦截。
        </p>
      </div>

      <!-- 结果区 -->
      <template v-if="replayStatus">
        <div class="block">
          <h2>测试结果</h2>
          <p class="run-line">
            replay_run <span class="mono">#{{ runId }}</span>
            状态 <span class="run-status" :class="`st-${replayStatus}`">{{ replayStatus }}</span>
          </p>
          <p class="muted status-legend">
            pass=全部通过（绿） fail=有失败（红） 预演=只规划未执行（灰） error=执行异常（橙）
          </p>
        </div>

        <!-- 断言明细表 -->
        <div v-if="runDetail?.assertion_results?.length" class="block">
          <h2>断言明细（{{ runDetail.assertion_results.length }}）</h2>
          <table class="tbl assert-tbl">
            <thead>
              <tr><th>kind</th><th>期望</th><th>观察</th><th>结果</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in runDetail.assertion_results" :key="i">
                <td><span class="chip chip-kind">{{ r.kind }}</span></td>
                <td class="mono">{{ assertExpect(r) }}</td>
                <td class="mono">{{ assertObserved(r) }}</td>
                <td>
                  <span v-if="r.skipped" class="skipped">skipped（{{ r.skipped }}）</span>
                  <span v-else-if="r.passed" class="ok">passed</span>
                  <span v-else class="ng">FAILED</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else-if="runDetail" class="block">
          <h2>断言明细</h2>
          <p class="muted">
            {{ replayStatus === "shadow" ? "shadow run 未执行，无断言结果。" : "无断言结果。" }}
          </p>
        </div>

        <!-- 失败归因 -->
        <div v-if="runDetail?.attribution" class="block">
          <h2>失败归因</h2>
          <pre class="code attribution">{{ runDetail.attribution }}</pre>
        </div>

        <!-- 前后快照对比（S8 产物） -->
        <div v-if="snapshotDiff.length" class="block">
          <h2>测试前后快照对比（forms）</h2>
          <p class="muted hint">只显示有差异的字段（前 10 行）。</p>
          <table class="tbl diff-tbl">
            <thead><tr><th>字段</th><th>before → after</th></tr></thead>
            <tbody>
              <tr v-for="(d, i) in snapshotDiff" :key="i">
                <td>{{ d.label }}</td>
                <td class="mono">{{ d.from }} → {{ d.to }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
  </section>
</template>

<style scoped>
/* S16 块 Q：表格/chip/代码块/分区块卡片/按钮走全局令牌类，这里只留回放布局 */
header h1 {
  margin: 0 0 var(--space-1);
  font-size: 20px;
}
header p {
  margin-top: 0;
}
.gate-hint {
  margin-top: var(--space-1);
  font-size: 12px;
}
.hint {
  margin-top: 0;
  font-size: 12px;
}
.override-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 480px;
}
.override-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ov-name {
  min-width: 140px;
  font-size: 13px;
}
.override-row input {
  flex: 1;
}
.modes {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mode {
  font-size: 13px;
}
/* C1 副作用确认：警示框 */
.confirm-box {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: 10px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-warning-border);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  font-size: 13px;
  color: var(--color-warning);
  max-width: 520px;
}
.block input[type="text"] {
  width: 220px;
}
/* 409 等安全拒绝：醒目拒绝卡 */
.reject {
  margin-top: var(--space-6);
  border: 1px solid var(--color-danger-border);
  border-radius: var(--radius-lg);
  padding: var(--space-3) var(--space-4);
  background: var(--color-danger-soft);
}
.reject h3 {
  margin: 0 0 6px;
  font-size: 14px;
  color: var(--color-danger);
}
.reject-409 {
  border-color: var(--color-warning-border);
  background: var(--color-warning-soft);
}
.reject-409 h3 {
  color: var(--color-warning);
}
.run-line {
  font-size: 15px;
}
/* run 状态大字：四态分色 */
.run-status {
  display: inline-block;
  font-size: 22px;
  font-weight: 700;
  padding: 0 10px;
  border-radius: var(--radius-md);
  vertical-align: middle;
}
.st-pass {
  color: var(--color-success);
}
.st-fail {
  color: var(--color-danger);
}
.st-shadow {
  color: var(--color-gray-5);
}
.st-error {
  color: var(--color-warning);
}
.status-legend {
  font-size: 12px;
}
/* 断言结果三态 */
.ok {
  color: var(--color-success);
}
.ng {
  color: var(--color-danger);
  font-weight: 700;
}
.skipped {
  color: var(--color-gray-5);
}
</style>
