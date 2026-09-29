<script setup lang="ts">
// S39b：App 壳极简化——登录页独立渲染，其余全部由 GraphWorkspace 承载
// （左树=唯一导航，旧侧栏已删除）。登出按钮在 GraphWorkspace 左树底部。
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { logout } from "./api";

const route = useRoute();
const router = useRouter();
const isLogin = computed(() => route.path === "/login");

async function doLogout(): Promise<void> {
  await logout();
  router.push("/login");
}
</script>

<template>
  <div class="shell" :class="{ bare: isLogin }">
    <RouterView />
  </div>
</template>

<style scoped>
.shell {
  height: 100vh;
  overflow: hidden;
}
</style>
