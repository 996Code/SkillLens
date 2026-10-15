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
              {{ a.lints.length ? `${a.lints.length} 项提示` : '合规' }}
            </span>
          </div>
          <div class="meta">
            <span class="mono">{{ hostOf(a.base_url) }}</span><b class="port">:{{ portOf(a.base_url) }}</b>
          </div>
          <div class="meta small">
            <span class="chip">探针 {{ a.probe_count }}</span>
            <span class="chip">流程 {{ a.flow_count }}</span>
            <span class="chip">业务链 {{ a.chain_count }}</span>
            <span class="chip" :class="a.has_login ? 'ok-chip' : 'warn-chip'">
              {{ a.has_login ? '已配登录' : '未配登录' }}
            </span>
          </div>
          <!-- 审查 C 批：警告去噪——全部同文案时不逐条重复，一条汇总+tooltip -->
          <div v-if="a.lints.length" class="lint" :title="a.lints.join('\n')">
            ⚠ {{ lintSummary(a) }}
          </div>
        </div>
      </div>

      <div v-if="selected" class="editor">
        <h3>{{ selected.label }}（{{ selected.id }}）</h3>
        <textarea v-model="yamlText" rows="18" spellcheck="false" />
        <div class="actions">
          <button @click="validate">校验</button>
          <button class="primary" :disabled="saving || yamlFor !== selected.id" @click="save">
            {{ saving ? "保存中…" : "保存" }}
          </button>
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
// yamlText 对应的 adapter id——加载失败/未加载时为 null，保存按钮据此门控
// （防串档：A 的 YAML 被 PUT 到 B 上静默毁掉 B 的配置）
const yamlFor = ref<string | null>(null);
const saving = ref(false);
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

// 审查 C 批：URL 拆解——端口高亮（8 个地址仅端口不同）
function hostOf(url: string): string {
  try { return new URL(url).host; } catch { return url; }
}
function portOf(url: string): string {
  try { return new URL(url).port || "80"; } catch { return ""; }
}
// 警告去噪：同文案去重为一条；不同文案只显示第一条+计数
function lintSummary(a: AdapterSummary): string {
  const uniq = [...new Set(a.lints.map(l => l.replace(/password_literal.*/, "凭据为明文字面量")))];
  if (uniq.length === 1) return uniq[0];
  return `${uniq[0]}（共 ${a.lints.length} 项）`;
}

async function select(a: AdapterSummary): Promise<void> {
  selected.value = a;
  feedback.value = null;
  yamlText.value = "";
  yamlFor.value = null;
  try {
    const res = await authedFetch(`/api/v1/adapters/${a.id}/yaml`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    if (selected.value?.id !== a.id) return; // 已切到别的清单，丢弃晚到响应
    yamlText.value = body.yaml;
    yamlFor.value = a.id;
  } catch (e: any) {
    if (selected.value?.id !== a.id) return;
    feedback.value = { ok: false, msg: `清单加载失败：${e.message}` };
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
  if (!selected.value || yamlFor.value !== selected.value.id || saving.value) return;
  saving.value = true;
  try {
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
  } catch (e: any) {
    feedback.value = { ok: false, msg: `保存请求失败：${e.message}` };
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.page { padding: 20px; }
.hint { color: var(--color-gray-6); font-size: 13px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 10px; padding: 14px; cursor: pointer; }
.card:hover { border-color: var(--color-primary); }
.row { display: flex; justify-content: space-between; align-items: center; }
.name { font-weight: 600; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; }
.badge.ok { background: var(--color-success-soft); color: var(--color-success, #15803d); }
.badge.warn { background: var(--color-warning-soft); color: var(--color-warning, #b45309); }
.meta { color: var(--color-gray-6); font-size: 12px; margin-top: 4px; }
.meta .port {
  color: var(--color-primary);
  font-weight: 700;
  font-size: 12px;
}
.meta .chip {
  display: inline-block;
  border: 1px solid var(--color-gray-3);
  border-radius: 4px;
  padding: 0 5px;
  margin: 1px 4px 1px 0;
  font-size: 11px;
}
.meta .ok-chip {
  color: var(--color-success);
  border-color: var(--color-success-border);
}
.meta .warn-chip {
  color: var(--color-warning);
  border-color: var(--color-warning-border);
}
.meta.small { font-size: 11px; }
.lint { color: var(--color-warning, #b45309); font-size: 11px; margin-top: 4px; }
.editor { margin-top: 20px; }
textarea { width: 100%; font: 12px/1.6 Consolas, monospace; border: 1px solid var(--color-border); border-radius: 8px; padding: 12px; }
.actions { margin-top: 8px; display: flex; gap: 8px; align-items: center; }
button { padding: 6px 18px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); cursor: pointer; }
button.primary { background: var(--color-primary); color: var(--color-surface); border-color: var(--color-primary); }
.ok-text { color: var(--color-success); font-size: 13px; }
.err-text { color: var(--color-danger); font-size: 13px; }
.loading { color: var(--color-gray-6); }
</style>
