<script setup lang="ts">
// 用户管理（admin）：多账号基础——建号/改角色/重置密码/删除。
// UI 体检遗留缺口收口；角色语义见 docs/arch/2026-10-08-auth-and-role-matrix.md。
import { computed, onMounted, ref } from "vue";
import { createUser, currentUser, deleteUser, listUsers,
         updateUser } from "../api";
import type { AuthUser } from "../api";
import { toastOk, toastErr } from "../toast";
import { askConfirm } from "../confirm";

const me = currentUser();
const isAdmin = computed(() => me?.role === "admin");

const users = ref<AuthUser[]>([]);
const loading = ref(true);
const error = ref("");

const newName = ref("");
const newPass = ref("");
const newRole = ref<AuthUser["role"]>("viewer");
const creating = ref(false);

const ROLE_LABEL: Record<AuthUser["role"], string> = {
  admin: "管理员", reviewer: "评审员", viewer: "只读",
};

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    users.value = await listUsers();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function create(): Promise<void> {
  if (!newName.value.trim() || newPass.value.length < 8) {
    toastErr("用户名必填，密码至少 8 位");
    return;
  }
  creating.value = true;
  try {
    await createUser(newName.value.trim(), newPass.value, newRole.value);
    toastOk(`已创建 ${newName.value}（${ROLE_LABEL[newRole.value]}）`);
    newName.value = "";
    newPass.value = "";
    await load();
  } catch (e) {
    toastErr(`创建失败：${e instanceof Error ? e.message : e}`);
  } finally {
    creating.value = false;
  }
}

async function changeRole(u: AuthUser, role: AuthUser["role"]): Promise<void> {
  // 审查 C 批：角色直改风险——加确认（尤其自我降权）
  const warn = u.id === me?.id
    ? `将你自己的角色改为「${ROLE_LABEL[role]}」。${role === "viewer" ? "降为只读后将无法再管理用户！" : ""}确定？`
    : `将 ${u.username} 的角色改为「${ROLE_LABEL[role]}」，确定？`;
  if (!(await askConfirm(warn))) {
    await load();  // 恢复下拉显示值
    return;
  }
  try {
    await updateUser(u.id, { role });
    toastOk(`${u.username} 角色已改为 ${ROLE_LABEL[role]}`);
    await load();
  } catch (e) {
    toastErr(`改角色失败：${e instanceof Error ? e.message : e}`);
    await load();
  }
}

async function resetPassword(u: AuthUser): Promise<void> {
  const pw = window.prompt(`为 ${u.username} 设置新密码（至少 8 位）：`);
  if (!pw) return;
  if (pw.length < 8) { toastErr("密码至少 8 位"); return; }
  try {
    await updateUser(u.id, { password: pw });
    toastOk(`${u.username} 密码已重置（旧会话已吊销）`);
  } catch (e) {
    toastErr(`重置失败：${e instanceof Error ? e.message : e}`);
  }
}

async function remove(u: AuthUser): Promise<void> {
  if (!(await askConfirm(`确定删除用户 ${u.username}？该操作不可恢复。`))) return;
  try {
    await deleteUser(u.id);
    toastOk(`已删除 ${u.username}`);
    await load();
  } catch (e) {
    toastErr(`删除失败：${e instanceof Error ? e.message : e}`);
  }
}

onMounted(() => { if (isAdmin.value) void load(); });
</script>

<template>
  <section>
    <h1>用户管理</h1>
    <p class="muted page-desc">
      多账号协作：管理员建号与分配角色（管理员可执行一切；评审员可评审与执行；
      只读仅查看）。
    </p>

    <p v-if="!isAdmin" class="error">仅管理员可访问本页。</p>

    <template v-else>
      <div class="block">
        <h2>新建账号</h2>
        <div class="create-row">
          <input v-model="newName" type="text" placeholder="用户名"
                 aria-label="用户名" data-testid="um-name" />
          <input v-model="newPass" type="password" placeholder="密码（至少 8 位）"
                 aria-label="密码" data-testid="um-pass" />
          <select v-model="newRole" aria-label="角色" data-testid="um-role">
            <option value="viewer">只读</option>
            <option value="reviewer">评审员</option>
            <option value="admin">管理员</option>
          </select>
          <button class="btn btn-primary" :disabled="creating"
                  data-testid="um-create" @click="create">
            {{ creating ? "创建中…" : "创建" }}
          </button>
        </div>
      </div>

      <p v-if="loading" class="muted">加载中…</p>
      <p v-else-if="error" class="error">加载失败：{{ error }}</p>
      <div v-else class="block">
        <h2>账号（{{ users.length }}）</h2>
        <table class="tbl" data-testid="um-table">
          <thead>
            <tr><th>#</th><th>用户名</th><th>角色</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id" :data-testid="`um-row-${u.id}`">
              <td>{{ u.id }}</td>
              <td>{{ u.username }}<span v-if="u.id === me?.id" class="muted">（我）</span></td>
              <td>
                <select :value="u.role" aria-label="角色"
                        :data-testid="`um-role-${u.id}`"
                        @change="changeRole(u, ($event.target as HTMLSelectElement).value as AuthUser['role'])">
                  <option value="viewer">只读</option>
                  <option value="reviewer">评审员</option>
                  <option value="admin">管理员</option>
                </select>
              </td>
              <td class="um-actions">
                <button class="btn btn-sm" title="设置新密码（旧会话立即失效）"
                        @click="resetPassword(u)">重置密码</button>
                <button v-if="u.id === me?.id" class="btn btn-sm" disabled
                        title="不能删除自己">删除</button>
                <button v-else class="btn btn-sm btn-danger"
                        title="删除该账号（不可恢复）"
                        @click="remove(u)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.create-row {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.create-row input {
  flex: 1;
  min-width: 160px;
  max-width: 260px;
}
.um-actions {
  display: flex;
  gap: var(--space-2);  /* 审查：误点防线——8px → 12px */
}
</style>
