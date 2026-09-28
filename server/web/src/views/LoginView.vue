<script setup lang="ts">
// S21 块 S：登录页——唯一免认证页面。成功存 token+user 跳 /skills；
// 失败显示错误（401 用户名/密码错）。空库无账号时提示联系管理员建号。
import { ref } from "vue";
import { useRouter } from "vue-router";
import { login } from "../api";

const router = useRouter();
const username = ref("");
const password = ref("");
const error = ref("");
const submitting = ref(false);

async function submit(): Promise<void> {
  if (!username.value.trim() || !password.value) {
    error.value = "请输入用户名和密码";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    await login(username.value.trim(), password.value);
    router.push("/dashboard");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-page" data-testid="login-page">
    <form class="login-card" data-testid="login-form" @submit.prevent="submit">
      <h1>SkillLens 登录</h1>
      <label class="form-row">
        用户名
        <input
          v-model="username"
          type="text"
          autocomplete="username"
          data-testid="login-username"
        />
      </label>
      <label class="form-row">
        密码
        <input
          v-model="password"
          type="password"
          autocomplete="current-password"
          data-testid="login-password"
        />
      </label>
      <button
        type="submit"
        class="btn btn-primary"
        :disabled="submitting"
        data-testid="login-submit"
      >
        {{ submitting ? "登录中…" : "登录" }}
      </button>
      <p v-if="error" class="error" data-testid="login-error">{{ error }}</p>
      <p class="hint">账号由管理员创建（admin 可在登录后建号）</p>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: var(--color-bg, #f5f6f8);
}
.login-card {
  width: 320px;
  padding: 32px 28px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.login-card h1 {
  font-size: 20px;
  margin: 0 0 6px;
}
.form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #555;
}
.form-row input {
  padding: 8px 10px;
  border: 1px solid #ccc;
  border-radius: 6px;
  font-size: 14px;
}
.error {
  color: #c0392b;
  font-size: 13px;
  margin: 0;
}
.hint {
  color: #999;
  font-size: 12px;
  margin: 0;
}
</style>
