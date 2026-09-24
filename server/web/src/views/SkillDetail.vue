<script setup lang="ts">
// Task 3（S9 块C）：skill 详情——GET /skills/{id}/card 一次聚合，分区展示。
// 只读边界：不出现任何编辑入口。
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { getSkillCard } from "../api";
import type { AssertionRow, SkillCard } from "../api";

const route = useRoute();
const card = ref<SkillCard | null>(null);
const loading = ref(true);
const notFound = ref(false);
const error = ref("");

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
});
</script>

<template>
  <section>
    <p v-if="loading" class="muted">加载中…</p>
    <div v-else-if="notFound" class="empty">
      <h1>404</h1>
      <p>Skill 不存在（可能已被 re-induce 重建，<RouterLink to="/skills">返回列表</RouterLink>）。</p>
    </div>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else-if="card">
      <!-- 概要 -->
      <header class="summary">
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
        </dl>
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

      <!-- 断言表 -->
      <div class="block">
        <h2>断言（{{ card.assertions.length }}）</h2>
        <p v-if="card.assertions.length === 0" class="muted">无</p>
        <table v-else class="tbl">
          <thead><tr><th>kind</th><th>layer</th><th>期望</th></tr></thead>
          <tbody>
            <tr v-for="a in card.assertions" :key="a.id">
              <td><span class="chip chip-kind">{{ a.kind }}</span></td>
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
            <dd><span class="dot" :class="`dot-${card.last_run.status}`"></span>{{ card.last_run.status }}</dd>
          </div>
          <div><dt>模式</dt><dd>{{ card.last_run.mode }}</dd></div>
          <div><dt>时间</dt><dd>{{ fmtTime(card.last_run.ts) }}</dd></div>
        </dl>
      </div>

      <!-- 页脚：回放入口（Task 5，U1 缓解：详情页给"接下来做什么"的显式引导） -->
      <footer class="replay-cta">
        <RouterLink :to="`/replay/${card.id}`" class="replay-btn">回放此 Skill</RouterLink>
        <span class="muted">触发 shadow/execute 回放并查看断言结果、前后快照对比。</span>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.summary h1 {
  margin: 0 0 4px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.desc {
  color: #666;
  margin-top: 0;
}
.meta {
  margin: 8px 0;
  display: flex;
  flex-wrap: wrap;
  gap: 24px;
}
.meta dt {
  font-size: 12px;
  color: #888;
}
.meta dd {
  margin: 2px 0 0;
}
.notes {
  font-size: 13px;
  color: #8a6d3b;
}
.block {
  margin-top: 28px;
}
.block h2 {
  font-size: 16px;
  border-bottom: 1px solid #eee;
  padding-bottom: 6px;
}
.block h3 {
  font-size: 14px;
  margin-bottom: 4px;
}
.code {
  background: #f6f8fa;
  border: 1px solid #e3e6ea;
  border-radius: 6px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  font-size: 13px;
  overflow-x: auto;
}
.code code {
  display: block;
  white-space: pre-wrap;
  word-break: break-all;
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
.mono {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
  word-break: break-all;
}
.chip {
  display: inline-block;
  background: #eef2f7;
  border-radius: 4px;
  padding: 0 6px;
  margin: 0 6px 2px 0;
  font-size: 12px;
}
.chip-kind {
  font-family: ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace;
}
.badge {
  font-size: 12px;
  font-weight: normal;
  padding: 1px 8px;
  border-radius: 10px;
}
.badge-learned {
  color: #1e7e34;
  background: #e6f4ea;
}
.badge-candidate {
  color: #555;
  background: #eee;
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}
.dot-pass {
  background: #1e7e34;
}
.dot-fail {
  background: #c62828;
}
.dot-shadow {
  background: #9e9e9e;
}
.dot-error {
  background: #e65100;
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
.replay-cta {
  margin-top: 36px;
  padding-top: 14px;
  border-top: 1px solid #eee;
  display: flex;
  align-items: center;
  gap: 12px;
}
.replay-btn {
  display: inline-block;
  padding: 6px 18px;
  border: 1px solid #185abc;
  background: #185abc;
  color: #fff;
  border-radius: 6px;
  text-decoration: none;
  font-size: 13px;
}
.replay-btn:hover {
  background: #1249a8;
}
</style>
