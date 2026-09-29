<script setup lang="ts">
// 工作台壳（S16 块 Q UI 升级）：深色左侧边栏导航（品牌 + 6 项带图标字符）
// + 独立滚动内容区。图标用 CSS ::before 生成（不进 textContent，测试即规格）。
// 只读边界：S14 起画布为唯一编排入口（主计划块 H 授权），其余导航保持只读；
// S15 评审为夜间 agent_run 的 PR 式评审流（区别于 Reports 发版四分类）。
// S21 块 S：登录页隐藏侧边栏；侧边栏底部显示当前用户 + 登出。
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { currentUser, logout } from "./api";

const route = useRoute();
const router = useRouter();
const isLogin = computed(() => route.path === "/login");
// 依赖 isLogin：路由变化时重取（登录成功跳转后 App 壳不重挂载）
const user = computed(() => (isLogin.value ? null : currentUser()));

async function doLogout(): Promise<void> {
  await logout();
  router.push("/login");
}
</script>

<template>
  <div class="shell" :class="{ bare: isLogin }">
    <aside v-if="!isLogin" class="sidebar">
      <div class="brand">SkillLens</div>
      <nav>
        <RouterLink to="/dashboard">仪表盘</RouterLink>
        <RouterLink to="/skills">操作流程</RouterLink>
        <RouterLink to="/reports/1">Reports</RouterLink>
        <RouterLink to="/audit">审计</RouterLink>
        <RouterLink to="/canvas">编排</RouterLink>
        <RouterLink to="/reviews-portal">评审</RouterLink>
        <RouterLink to="/suites">套件</RouterLink>
        <RouterLink to="/timeline">链路</RouterLink>
      </nav>
      <div class="sidebar-foot">
        <div class="whoami" data-testid="current-user">
          {{ user?.username }}（{{ user?.role }}）
        </div>
        <button class="logout-btn" data-testid="logout-btn" @click="doLogout">
          登出
        </button>
        <div class="tagline">变更智能工作台</div>
      </div>
    </aside>
    <main class="content">
      <div class="page">
        <RouterView />
      </div>
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden; /* 内容区独立滚动 */
}
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--color-sidebar);
  color: var(--color-sidebar-text);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
.brand {
  padding: 20px var(--space-4);
  font-weight: 700;
  font-size: 16px;
  letter-spacing: 0.02em;
  color: #fff;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-3) var(--space-2);
}
nav a {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px var(--space-3);
  border-radius: var(--radius-md);
  color: var(--color-sidebar-text);
  text-decoration: none;
  font-size: 14px;
  transition: background 0.15s ease, color 0.15s ease;
}
/* 图标字符（::before 不计入 textContent）*/
nav a::before {
  display: inline-block;
  width: 20px;
  text-align: center;
  font-size: 15px;
  opacity: 0.85;
}
nav a:nth-child(1)::before {
  content: "◆";
}
nav a:nth-child(2)::before {
  content: "▤";
}
nav a:nth-child(3)::before {
  content: "⌕";
}
nav a:nth-child(4)::before {
  content: "⬡";
}
nav a:nth-child(5)::before {
  content: "✓";
}
nav a:nth-child(6)::before {
  content: "✓";
}
nav a:nth-child(7)::before {
  content: "⌇";
}
nav a:nth-child(8)::before {
  content: "▤";
}
nav a:hover {
  background: var(--color-sidebar-hover);
  color: #fff;
}
nav a.router-link-active {
  background: var(--color-primary);
  color: #fff;
}
.sidebar-foot {
  margin-top: auto;
  padding: var(--space-3) var(--space-4);
  font-size: 12px;
  color: var(--color-gray-5);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.whoami {
  margin-bottom: 6px;
  color: var(--color-sidebar-text);
}
.logout-btn {
  width: 100%;
  padding: 6px 0;
  margin-bottom: 8px;
  background: transparent;
  color: var(--color-gray-5);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
}
.logout-btn:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.5);
}
.content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-6) var(--space-8);
}
.page {
  max-width: 1100px;
  margin: 0 auto;
}
</style>
