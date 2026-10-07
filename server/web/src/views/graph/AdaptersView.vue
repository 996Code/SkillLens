<template>
  <div class="page">
    <h2>系统接入清单</h2>
    <p class="hint">目标系统以声明式清单接入（YAML）：登录 / 探针 / 业务链。新系统接入零手写编排脚本。</p>

    <div v-if="loading" class="loading">加载中…</div>
    <template v-else>
      <div class="grid">
        <div v-for="a in adapters" :key="a.id" class="card" @click="select(a)">
          <div class="row">
            <span class="name">{{ a.label }}</span>
            <span class="badge" :class="a.lints.length ? 'warn' : 'ok'">
              {{ a.lints.length ? '有警告' : '合规' }}
            </span>
          </div>
          <div class="meta">{{ a.base_url }}</div>
          <div class="meta small">
            探针 {{ a.probe_count }} · 流程 {{ a.flow_count }} · 链 {{ a.chain_count }}
            · {{ a.has_login ? '已配登录' : '无登录' }}
          </div>
          <div v-for="l in a.lints" :key="l" class="lint">⚠ {{ l }}</div>
        </div>
      </div>

      <div v-if="selected" class="editor">
        <h3>{{ selected.label }}（{{ selected.id }}）</h3>
        <textarea v-model="yamlText" rows="18" spellcheck="false" />
        <div class="actions">
          <button @click="validate">校验</button>
          <button class="primary" @click="save">保存</button>
          <span v-if="feedback" :class="feedback.ok ? 'ok-text' : 'err-text'">
            {{ feedback.msg }}
          </span>
        </div>
      </div>

      <!-- P2 交互画像指纹：贴系统页面 HTML → 识别组件库 → 生成画像 YAML 片段 -->
      <div class="fingerprint">
        <h3>交互画像指纹识别</h3>
        <p class="hint">接入新系统：贴一段系统页面 HTML（查看源代码任意表单/列表区域），自动识别组件库并生成交互画像（interaction_profile）——贴进上方清单即完成适配。</p>
        <textarea v-model="fpDom" rows="6" placeholder="<div class='ant-modal-content'>…（系统页面 HTML 片段）" spellcheck="false" />
        <div class="actions">
          <button @click="fingerprint">识别画像</button>
          <span v-if="fpResult" class="ok-text">
            组件库：{{ fpResult.fingerprint.ui_library }}
            · 框架：{{ fpResult.fingerprint.framework }}
          </span>
        </div>
        <textarea v-if="fpYaml" v-model="fpYaml" rows="10" spellcheck="false" class="fp-out" />
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { authedFetch } from "../../api";

interface AdapterSummary {
  id: string; label: string; base_url: string;
  has_login: boolean; probe_count: number; flow_count: number;
  chain_count: number; lints: string[];
}

const adapters = ref<AdapterSummary[]>([]);
const loading = ref(true);
const selected = ref<AdapterSummary | null>(null);
const yamlText = ref("");
const feedback = ref<{ ok: boolean; msg: string } | null>(null);

const fpDom = ref("");
const fpYaml = ref("");
const fpResult = ref<{ fingerprint: { ui_library: string; framework: string } } | null>(null);

async function fingerprint(): Promise<void> {
  try {
    const res = await authedFetch("/api/v1/adapters/fingerprint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dom: fpDom.value, url: "" }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    fpResult.value = body;
    fpYaml.value = body.profile_yaml || "";
  } catch (e: any) {
    fpYaml.value = "";
    fpResult.value = null;
  }
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    const res = await authedFetch("/api/v1/adapters");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    adapters.value = await res.json();
  } catch {
    adapters.value = [];
  } finally {
    loading.value = false;
  }
}

async function select(a: AdapterSummary): Promise<void> {
  selected.value = a;
  feedback.value = null;
  const res = await authedFetch(`/api/v1/adapters/${a.id}/yaml`);
  if (res.ok) {
    const body = await res.json();
    yamlText.value = body.yaml;
  }
}

async function validate(): Promise<void> {
  try {
    const res = await authedFetch("/api/v1/adapters/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml: yamlText.value }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    feedback.value = body.valid
      ? { ok: true, msg: "校验通过" + (body.lints?.length ? `（${body.lints.length} 条警告）` : "") }
      : { ok: false, msg: `校验失败：${body.error}` };
  } catch (e: any) {
    feedback.value = { ok: false, msg: `校验请求失败：${e.message}` };
  }
}

async function save(): Promise<void> {
  if (!selected.value) return;
  const res = await authedFetch(`/api/v1/adapters/${selected.value.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml: yamlText.value }),
  });
  if (res.ok) {
    feedback.value = { ok: true, msg: "已保存" };
    await load();
  } else {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    feedback.value = { ok: false, msg: `保存失败：${body.detail || ""}` };
  }
}

onMounted(load);
</script>

<style scoped>
.page { padding: 20px; }
.hint { color: #6b7280; font-size: 13px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.card { background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; cursor: pointer; }
.card:hover { border-color: #2563eb; }
.row { display: flex; justify-content: space-between; align-items: center; }
.name { font-weight: 600; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.warn { background: #fef3c7; color: #92400e; }
.meta { color: #6b7280; font-size: 12px; margin-top: 4px; }
.meta.small { font-size: 11px; }
.lint { color: #92400e; font-size: 11px; margin-top: 4px; }
.editor { margin-top: 20px; }
textarea { width: 100%; font: 12px/1.6 Consolas, monospace; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; }
.actions { margin-top: 8px; display: flex; gap: 8px; align-items: center; }
button { padding: 6px 18px; border: 1px solid #e5e7eb; border-radius: 8px; background: #fff; cursor: pointer; }
button.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.ok-text { color: #16a34a; font-size: 13px; }
.err-text { color: #dc2626; font-size: 13px; }
.loading { color: #6b7280; }
</style>
