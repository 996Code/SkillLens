<script setup lang="ts">
// S42-7 字段类型知识库维护：表单校验自愈资产（回放遇校验拦截时按
// 类型生成合法值换值重试；自愈成功自动反哺 learned 条目）。
import { onMounted, ref } from "vue";
import {
  createFieldType,
  deleteFieldType,
  listFieldTypes,
  updateFieldType,
} from "../api";
import type { FieldTypeHintItem } from "../api";
import { currentUser } from "../api";

const items = ref<FieldTypeHintItem[]>([]);
const builtinTypes = ref<string[]>([]);
const loading = ref(true);
const error = ref("");
const user = currentUser();
const canEdit = user?.role === "admin" || user?.role === "reviewer";

// 新建
const newPattern = ref("");
const newType = ref("phone");
const newExample = ref("");
const creating = ref(false);
const createError = ref("");

// 编辑
const editingId = ref<number | null>(null);
const editPattern = ref("");
const editType = ref("");
const editExample = ref("");
const busy = ref(false);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const d = await listFieldTypes();
    items.value = d.items;
    builtinTypes.value = d.builtin_types;
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(() => void load());

async function create(): Promise<void> {
  if (!newPattern.value.trim()) {
    createError.value = "请填写字段匹配模式";
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createFieldType(newPattern.value.trim(), newType.value, newExample.value.trim());
    newPattern.value = "";
    newExample.value = "";
    await load();
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e);
  } finally {
    creating.value = false;
  }
}

function startEdit(r: FieldTypeHintItem): void {
  editingId.value = r.id;
  editPattern.value = r.label_pattern;
  editType.value = r.field_type;
  editExample.value = r.example_value;
}

async function saveEdit(): Promise<void> {
  if (editingId.value == null) return;
  busy.value = true;
  try {
    await updateFieldType(editingId.value, editPattern.value.trim(),
                          editType.value, editExample.value.trim());
    editingId.value = null;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function remove(id: number): Promise<void> {
  busy.value = true;
  try {
    await deleteFieldType(id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

const sourceBadge: Record<string, string> = {
  manual: "badge-learned",
  learned: "badge-candidate",
};
</script>

<template>
  <section>
    <h1>字段类型知识库</h1>
    <p class="muted page-desc">
      表单校验自愈资产：回放遇 JS 校验拦截时按字段类型生成合法值换值重试；
      自愈成功自动沉淀（learned）并累计成功次数。人工可维护补充领域规则。
    </p>

    <p v-if="loading" class="muted">加载中…</p>
    <p v-else-if="error" class="error">加载失败：{{ error }}</p>

    <template v-else>
      <!-- 新建 -->
      <div v-if="canEdit" class="block" data-testid="ft-create">
        <h2>新增规则</h2>
        <div class="ft-form-row">
          <input v-model="newPattern" placeholder="字段匹配模式（如：手机）" data-testid="ft-new-pattern" />
          <select v-model="newType" data-testid="ft-new-type">
            <option v-for="t in builtinTypes" :key="t" :value="t">{{ t }}</option>
          </select>
          <input v-model="newExample" placeholder="示例值（可选）" />
          <button class="btn btn-primary" :disabled="creating" data-testid="ft-create-btn" @click="create">
            {{ creating ? "保存中…" : "新增" }}
          </button>
        </div>
        <p v-if="createError" class="error">{{ createError }}</p>
      </div>

      <!-- 列表 -->
      <div class="block" data-testid="ft-list">
        <h2>规则（{{ items.length }}）</h2>
        <p v-if="!items.length" class="muted">
          暂无沉淀规则——回放自愈成功后会自动出现在这里
        </p>
        <table v-else class="tbl">
          <thead>
            <tr><th>字段匹配</th><th>类型</th><th>示例值</th><th>来源</th><th>成功次数</th><th v-if="canEdit"></th></tr>
          </thead>
          <tbody>
            <tr v-for="r in items" :key="r.id" :data-testid="`ft-row-${r.id}`">
              <template v-if="editingId === r.id">
                <td><input v-model="editPattern" /></td>
                <td>
                  <select v-model="editType">
                    <option v-for="t in builtinTypes" :key="t" :value="t">{{ t }}</option>
                  </select>
                </td>
                <td><input v-model="editExample" /></td>
                <td><span class="badge" :class="sourceBadge[r.source] || ''">{{ r.source }}</span></td>
                <td class="mono">{{ r.success_count }}</td>
                <td v-if="canEdit">
                  <button class="btn btn-sm" :disabled="busy" @click="saveEdit">保存</button>
                  <button class="btn btn-sm" :disabled="busy" @click="editingId = null">取消</button>
                </td>
              </template>
              <template v-else>
                <td class="mono">{{ r.label_pattern }}</td>
                <td><span class="badge badge-kind">{{ r.field_type }}</span></td>
                <td class="mono">{{ r.example_value || "—" }}</td>
                <td>
                  <span class="badge" :class="sourceBadge[r.source] || ''">{{ r.source }}</span>
                  <span v-if="r.source_skill_id" class="muted">← skill #{{ r.source_skill_id }}</span>
                </td>
                <td class="mono">{{ r.success_count }}</td>
                <td v-if="canEdit">
                  <button class="btn btn-sm" :disabled="busy" @click="startEdit(r)">编辑</button>
                  <button class="btn btn-sm btn-danger" :disabled="busy" @click="remove(r.id)">删除</button>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ft-form-row {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.ft-form-row input, .ft-form-row select {
  padding: 5px 10px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: 13px;
}
.ft-form-row input:first-child { min-width: 220px; }
.btn-danger { color: var(--color-danger); }
</style>
