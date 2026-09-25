<script setup lang="ts">
// 工作台壳：顶部导航（Skills / Reports / 审计 / 画布 / 评审）+ 路由出口。
// 只读边界：S14 起画布为唯一编排入口（主计划块 H 授权），其余导航保持只读；
// S15 评审为夜间 agent_run 的 PR 式评审流（区别于 Reports 发版四分类）。
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <span class="brand">SkillLens</span>
      <nav>
        <RouterLink to="/skills">Skills</RouterLink>
        <RouterLink to="/reports/1">Reports</RouterLink>
        <RouterLink to="/audit">审计</RouterLink>
        <RouterLink to="/canvas">画布</RouterLink>
        <RouterLink to="/reviews-portal">评审</RouterLink>
      </nav>
    </header>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
}
.topbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 10px 20px;
  border-bottom: 1px solid #ddd;
  background: #fafafa;
}
.brand {
  font-weight: 700;
}
nav {
  display: flex;
  gap: 16px;
}
nav a {
  color: #444;
  text-decoration: none;
  padding: 4px 8px;
  border-radius: 4px;
}
nav a.router-link-active {
  color: #185abc;
  background: #e8f0fe;
}
.content {
  padding: 20px;
  max-width: 1100px;
  margin: 0 auto;
}
</style>
