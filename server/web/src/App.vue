<script setup lang="ts">
// 工作台壳：顶部导航（Skills / Reports）+ 路由出口。
// 只读边界：导航不出现任何编辑入口（宪法 §0.3 / 计划 Global Constraints）。
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <span class="brand">SkillLens</span>
      <nav>
        <RouterLink to="/skills">Skills</RouterLink>
        <RouterLink to="/reports/1">Reports</RouterLink>
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
