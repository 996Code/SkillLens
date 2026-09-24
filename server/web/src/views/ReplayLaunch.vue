<script setup lang="ts">
// Task 5（S9 块C C3+C1 UI）：回放触发与结果。
// 提交走 POST /expected-deltas/{id}/observe（同步返回，无需轮询）；
// observe 的 replay 概要在响应里，断言明细/快照再取 GET /replay-runs/{id}。
// C1 门控：模式单选 shadow（默认）/execute + "我已确认副作用"复选，
// execute 时二者不齐禁用提交（二要素齐备才发 confirm_side_effect=true）。
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { getReplayRun, getSkillCard, replayObserve } from "../api";
import type { AssertionResult, ReplayRunDetail, SkillCard } from "../api";

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
const snapshotDiff = computed(() => {
  const run = runDetail.value;
  const before = run?.plan?.before_snapshot?.forms ?? [];
  const after = run?.plan?.after_snapshot?.forms ?? [];
  const afterByLabel = new Map(after.map((f) => [f.label, f.value]));
  return before
    .filter((f) => afterByLabel.get(f.label) !== f.value)
    .slice(0, 10)
    .map((f) => ({ label: f.label, from: f.value, to: afterByLabel.get(f.label) ?? "（字段已消失）" }));
});

/** 断言明细的人读期望/观察值。 */
function assertExpect(r: AssertionResult): string {
  const p = r.payload || {};
  switch (r.kind) {
    case "api_status":
      return `${p.api_template} → ${p.expect_status}`;
    case "state_signal":
      return `${p.field}=${p.expect_value}（${p.api_template}）`;
    case "ui_text":
      return `${p.label}: ${p.before} → ${p.after}`;
    case "field_change":
      return `${p.field}: ${p.before} → ${p.after}`;
    default:
      return JSON.stringify(p);
  }
}

function assertObserved(r: AssertionResult): string {
  return r.observed_status == null ? "—" : String(r.observed_status);
}

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
      <h1>404</h1>
      <p>Skill 不存在（<RouterLink to="/skills">返回列表</RouterLink>）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card">
      <header>
        <h1>回放 Skill #{{ card.id }}：{{ card.name }}</h1>
        <p class="muted">
          通过目标 delta 触发回放观测（observe）：server 会真实执行回放，
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
              <span><strong>shadow</strong>（默认）——只规划不执行，安全核验</span>
            </label>
            <label class="mode">
              <input v-model="mode" type="radio" value="execute" />
              <span><strong>execute</strong>——真实执行（含写操作副作用）</span>
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

        <button type="submit" :disabled="!canSubmit">
          {{ submitting ? "回放中…（回放在常驻浏览器窗口执行，完成后此处显示结果）" : "触发回放" }}
        </button>
        <p v-if="mode === 'execute' && !confirmed" class="muted gate-hint">
          勾选副作用确认后才能提交（C1 安全门控）。
        </p>
      </form>

      <!-- 409 等业务拒绝：友好展示 -->
      <div v-if="observeError" class="reject" :class="{ 'reject-409': observeErrorStatus === 409 }">
        <h3>{{ observeErrorStatus === 409 ? "回放未执行（安全拒绝）" : `请求失败${observeErrorStatus ? `（${observeErrorStatus}）` : ""}` }}</h3>
        <p class="mono">{{ observeError }}</p>
        <p v-if="observeErrorStatus === 409" class="muted">
          这是预期内的安全行为：observe 需要 execute 模式（勾选副作用确认）才会真实执行；
          "shadow run 未执行，无观测"即 shadow 计划被安全拦截。
        </p>
      </div>

      <!-- 结果区 -->
      <template v-if="replayStatus">
        <div class="block">
          <h2>回放结果</h2>
          <p class="run-line">
            replay_run <span class="mono">#{{ runId }}</span>
            状态 <span class="run-status" :class="`st-${replayStatus}`">{{ replayStatus }}</span>
          </p>
          <p class="muted status-legend">
            pass=全断言通过（绿） fail=有断言失败（红） shadow=只规划未执行（灰） error=执行异常（橙）
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
          <h2>回放前后快照对比（forms）</h2>
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
header h1 {
  margin: 0 0 4px;
  font-size: 20px;
}
header p {
  margin-top: 0;
}
.launch button[type="submit"] {
  padding: 8px 24px;
  border: 1px solid #185abc;
  background: #185abc;
  color: #fff;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
}
.launch button[type="submit"]:disabled {
  border-color: #bbb;
  background: #eee;
  color: #999;
  cursor: not-allowed;
}
.gate-hint {
  margin-top: 6px;
  font-size: 12px;
}
.block {
  margin-top: 20px;
}
.block h2 {
  font-size: 15px;
  border-bottom: 1px solid #eee;
  padding-bottom: 6px;
  margin-bottom: 8px;
}
.hint {
  margin-top: 0;
  font-size: 12px;
}
.override-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 13px;
}
.modes {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.mode {
  font-size: 13px;
}
.confirm-box {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid #e65100;
  border-radius: 6px;
  background: #fff3e0;
  font-size: 13px;
  color: #a04a00;
  max-width: 520px;
}
.block input[type="text"] {
  padding: 6px 10px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 13px;
  width: 220px;
}
.reject {
  margin-top: 20px;
  border: 1px solid #c62828;
  border-radius: 8px;
  padding: 10px 14px;
  background: #fdecea;
}
.reject h3 {
  margin: 0 0 6px;
  font-size: 14px;
  color: #c62828;
}
.reject-409 {
  border-color: #e65100;
  background: #fff3e0;
}
.reject-409 h3 {
  color: #a04a00;
}
.run-line {
  font-size: 15px;
}
.run-status {
  display: inline-block;
  font-size: 22px;
  font-weight: 700;
  padding: 0 10px;
  border-radius: 6px;
  vertical-align: middle;
}
.st-pass {
  color: #1e7e34;
}
.st-fail {
  color: #c62828;
}
.st-shadow {
  color: #9e9e9e;
}
.st-error {
  color: #e65100;
}
.status-legend {
  font-size: 12px;
}
.tbl {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
}
.tbl th,
.tbl td {
  border: 1px solid #e3e6ea;
  text-align: left;
  padding: 6px 10px;
  vertical-align: top;
}
.tbl th {
  background: #f6f8fa;
}
.chip {
  display: inline-block;
  background: #eef2f7;
  border-radius: 4px;
  padding: 0 6px;
  font-size: 12px;
}
.chip-kind {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
}
.ok {
  color: #1e7e34;
}
.ng {
  color: #c62828;
  font-weight: 700;
}
.skipped {
  color: #9e9e9e;
}
.code {
  background: #f6f8fa;
  border: 1px solid #e3e6ea;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  word-break: break-all;
}
.muted {
  color: #666;
}
.error {
  color: #c62828;
}
.empty h1 {
  margin-bottom: 4px;
}
</style>
