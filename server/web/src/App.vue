<script setup lang="ts">
// 工作台壳（S16 块 Q UI 升级）：深色左侧边栏导航（品牌 + 6 项带图标字符）
// + 独立滚动内容区。图标用 CSS ::before 生成（不进 textContent，测试即规格）。
// 只读边界：S14 起画布为唯一编排入口（主计划块 H 授权），其余导航保持只读；
// S15 评审为夜间 agent_run 的 PR 式评审流（区别于 Reports 发版四分类）。
</script>

<template>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">SkillLens</div>
      <nav>
        <RouterLink to="/skills">Skills</RouterLink>
        <RouterLink to="/reports/1">Reports</RouterLink>
        <RouterLink to="/audit">审计</RouterLink>
        <RouterLink to="/canvas">画布</RouterLink>
        <RouterLink to="/reviews-portal">评审</RouterLink>
      </nav>
      <div class="sidebar-foot">变更智能工作台</div>
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
