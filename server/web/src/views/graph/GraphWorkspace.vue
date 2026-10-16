<script setup lang="ts">
// S40 图工作台壳 v2：左树=分组折叠+搜索+系统徽标；中=RouterView。
// 修复 S39 的"文字墙"问题：62 个流程不再平铺，按系统分组可折叠，
// 顶部搜索框实时过滤。
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getSkills, listScenarios, listSuites, logout, currentUser } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";
import { groupBySystem } from "../../system-group";
import { useToasts } from "../../toast";
import { useConfirmReq, answerConfirm } from "../../confirm";
const confirmReq = useConfirmReq();

const user = currentUser();
const ROLE_LABEL: Record<string, string> = {
  admin: "管理员", reviewer: "评审员", viewer: "只读",
};

const toasts = useToasts();

const route = useRoute();
const router = useRouter();
const suites = ref<SuiteItem[]>([]);
// AQ2：场景计数（导航一级入口）
const scenarioCount = ref(0);
const skills = ref<SkillListItem[]>([]);
const loading = ref(true);
const search = ref("");
const collapsed = ref<Set<string>>(new Set());
// AQ2：步骤库默认收起（技术层降级）
const libraryCollapsed = ref(true);
// AR5：开发者工具默认收起（诊断资产）
const devCollapsed = ref(true);
const error = ref("");

const currentSkillId = computed(() =>
  route.name === "graph-skill" ? String(route.params.skillId) : "");

// 审查 C 批：深链页侧栏高亮错位（/graph 下前缀匹配劫持了总览高亮）
const isScenarioRunDeep = computed(() =>
  route.name === "scenario-run-detail");

// 按系统分组 + 搜索过滤（分组排序共享 system-group——双源漂移已消除）
const grouped = computed(() => {
  const q = search.value.trim().toLowerCase();
  return groupBySystem(
    skills.value,
    q ? (s) => s.name.toLowerCase().includes(q) : () => true);
});

function toggleGroup(sys: string): void {
  if (collapsed.value.has(sys)) collapsed.value.delete(sys);
  else collapsed.value.add(sys);
}

function isCollapsed(sys: string): boolean {
  return collapsed.value.has(sys);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    [suites.value, skills.value] = await Promise.all([listSuites(), getSkills()]);
    try { scenarioCount.value = (await listScenarios()).length; } catch { /* 计数 fail-open */ }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
onMounted(() => void load());

async function doLogout(): Promise<void> {
  await logout();
  router.push("/login");
}
</script>

<template>
  <div class="gw-shell" data-testid="graph-workspace">
    <aside class="gw-tree">
      <RouterLink to="/graph" class="gw-brand" data-testid="gw-overview-link">
        <span class="gw-brand-logo">SL</span>
        <span class="gw-brand-text">
          <span class="gw-brand-name">SkillLens</span>
          <span class="gw-brand-sub">测试工作台</span>
        </span>
      </RouterLink>

      <div class="gw-search">
        <input
          v-model="search"
          type="text"
          placeholder="搜索流程…"
          aria-label="搜索流程"
          data-testid="tree-search"
        />
      </div>

      <nav class="gw-nav">
        <!-- 主链：场景 → 运行 → 报告评审 -->
        <RouterLink to="/graph/scenarios" class="gw-item gw-item-primary"
                    data-testid="gw-scenarios-link">
          测试场景 <span class="gw-count">{{ scenarioCount }}</span>
        </RouterLink>
        <RouterLink to="/graph/scenario-runs" class="gw-item"
                    :class="{ 'router-link-active': isScenarioRunDeep }"
                    data-testid="gw-scenario-runs-link">
          场景运行
        </RouterLink>
        <RouterLink to="/graph/scenario-reports" class="gw-item"
                    data-testid="gw-reports-link">
          报告与评审
        </RouterLink>

        <div class="gw-sep"></div>
        <div class="gw-section-label">分析</div>
        <RouterLink to="/graph/timeline" class="gw-item">时间线</RouterLink>
        <RouterLink to="/graph/failures" class="gw-item">失败分析</RouterLink>

        <div class="gw-sep"></div>
        <div class="gw-section-label">管理</div>
        <RouterLink to="/graph/adapters" class="gw-item">系统接入</RouterLink>
        <RouterLink v-if="user?.role === 'admin'" to="/graph/users"
                    class="gw-item" data-testid="gw-users-link">用户管理</RouterLink>
      </nav>

      <!-- 步骤库（技术层——默认收起） -->
      <button class="gw-lib-head" data-testid="gw-lib-toggle"
              @click="libraryCollapsed = !libraryCollapsed">
        <span class="gw-toggle">{{ libraryCollapsed ? "▸" : "▾" }}</span>
        步骤库
        <span class="gw-count">{{ skills.length }}</span>
      </button>
      <div v-show="!libraryCollapsed" class="gw-tree-scroll">
        <div v-for="[sys, list] in grouped" :key="sys" class="gw-group">
          <button class="gw-group-head" @click="toggleGroup(sys)">
            <span class="gw-toggle">{{ isCollapsed(sys) ? "▸" : "▾" }}</span>
            <span class="gw-group-name">{{ sys }}</span>
            <span class="gw-count">{{ list.length }}</span>
          </button>
          <div v-if="!isCollapsed(sys)" class="gw-group-body">
            <RouterLink
              v-for="s in list"
              :key="s.id"
              :to="`/graph/skill/${s.id}`"
              class="gw-skill"
              :class="{ active: currentSkillId === String(s.id) }"
              :data-testid="`gw-skill-${s.id}`"
            >
              {{ s.name }}
            </RouterLink>
          </div>
        </div>
        <p v-if="grouped.length === 0 && !loading" class="gw-empty">无匹配流程</p>
      </div>

      <!-- 开发者工具（默认收起） -->
      <button class="gw-lib-head" data-testid="gw-dev-toggle"
              @click="devCollapsed = !devCollapsed">
        <span class="gw-toggle">{{ devCollapsed ? "▸" : "▾" }}</span>
        开发者工具
      </button>
      <div v-show="!devCollapsed" class="gw-dev-body">
        <RouterLink to="/graph/learning" class="gw-item">学习图</RouterLink>
        <RouterLink to="/graph/canvas" class="gw-item">编排画布</RouterLink>
        <RouterLink to="/graph/audit" class="gw-item">审计</RouterLink>
        <RouterLink to="/graph/reports" class="gw-item">旧版报告</RouterLink>
        <RouterLink to="/graph/field-types" class="gw-item">字段类型</RouterLink>
        <RouterLink to="/graph/suites" class="gw-item">分组（legacy）</RouterLink>
      </div>

      <div class="gw-tree-foot">
        <div class="gw-user" v-if="user">
          <span class="gw-user-avatar">{{ user.username.slice(0, 1).toUpperCase() }}</span>
          <span class="gw-user-name">{{ user.username }}</span>
          <span class="gw-user-role">{{ ROLE_LABEL[user.role] }}</span>
        </div>
        <button class="logout-btn" data-testid="logout-btn" @click="doLogout">
          登出
        </button>
      </div>
    </aside>

    <!-- 中：当前页面 -->
    <main class="gw-canvas">
      <p v-if="error" class="error">左树加载失败：{{ error }}</p>
      <RouterView @graph-changed="load" />
    </main>
  </div>

  <!-- UI 批3：确认弹层（替代 window.confirm——样式归体系） -->
  <div v-if="confirmReq" class="sl-confirm-mask" data-testid="confirm-mask">
    <div class="sl-confirm">
      <p>{{ confirmReq.message }}</p>
      <div class="sl-confirm-btns">
        <button class="btn" @click="answerConfirm(false)">取消</button>
        <button class="btn btn-primary" data-testid="confirm-ok"
                @click="answerConfirm(true)">确定</button>
      </div>
    </div>
  </div>
  <!-- 全局 toast（UI 批1）：成功/失败可见——静默吞错终结 -->
  <div class="sl-toasts" data-testid="global-toasts">
    <div v-for="t in toasts" :key="t.id" class="sl-toast" :class="`sl-toast-${t.kind}`">
      {{ t.text }}
    </div>
  </div>
</template>

<style scoped>
.gw-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.gw-tree {
  width: 232px;
  flex-shrink: 0;
  background: var(--color-sidebar);
  overflow-y: auto;
  padding: var(--space-3) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 品牌头：logo 方块 + 双行字 */
.gw-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--space-1) var(--space-2) var(--space-3);
  margin-bottom: var(--space-1);
  text-decoration: none;
}
.gw-brand-logo {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: linear-gradient(135deg, var(--color-primary) 0%,
    var(--color-sidebar-accent) 100%);
  color: #fff;
  font-weight: 800;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  box-shadow: 0 2px 8px rgba(109, 90, 230, 0.4);
}
.gw-brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.gw-brand-name {
  color: #fff;
  font-weight: 700;
  font-size: 14.5px;
  letter-spacing: -0.01em;
}
.gw-brand-sub {
  color: var(--color-sidebar-text);
  font-size: 11px;
  opacity: 0.75;
}
.gw-brand:hover .gw-brand-name { color: #fff; }

/* 搜索 */
.gw-search {
  padding: 0 var(--space-1) var(--space-2);
}
.gw-search input {
  width: 100%;
  padding: 6px 11px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-md);
  font-size: 13px;
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}
.gw-search input::placeholder {
  color: var(--color-sidebar-text);
  opacity: 0.7;
}
.gw-search input:focus {
  outline: none;
  border-color: var(--color-sidebar-accent);
  box-shadow: 0 0 0 3px rgba(139, 123, 243, 0.16);
}

/* 主导航：去图标——纯文字，靠字重/背景区分 */
.gw-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.gw-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  border-radius: var(--radius-md);
  font-size: 13.5px;
  font-weight: 500;
  color: var(--color-sidebar-text);
  text-decoration: none;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.gw-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
  text-decoration: none;
}
.gw-item.router-link-active {
  background: var(--color-sidebar-active);
  color: #fff;
  font-weight: 650;
  box-shadow: inset 3px 0 0 var(--color-sidebar-accent);
}
.gw-item-primary {
  font-weight: 650;
  font-size: 14px;
  color: #fff;
}
.gw-count {
  font-size: 11px;
  color: var(--color-sidebar-text);
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  padding: 1px 7px;
  font-variant-numeric: tabular-nums;
}
.gw-sep {
  height: 1px;
  background: rgba(255, 255, 255, 0.07);
  margin: var(--space-2) var(--space-1);
}
.gw-section-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--color-sidebar-text);
  opacity: 0.55;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 0 12px var(--space-1);
}

/* 折叠区头（步骤库/开发者） */
.gw-lib-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 12px;
  margin-top: var(--space-2);
  border: none;
  background: transparent;
  border-radius: var(--radius-md);
  font-size: 11.5px;
  font-weight: 700;
  color: var(--color-sidebar-text);
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.gw-lib-head:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}
.gw-dev-body {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.gw-dev-body .gw-item {
  font-size: 12.5px;
  padding: 5px 12px;
}

/* 步骤库滚动区 */
.gw-tree-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 60px;
}
.gw-group {
  margin-bottom: 1px;
}
.gw-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px 12px;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-sidebar-text);
  cursor: pointer;
}
.gw-group-head:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}
.gw-toggle {
  width: 12px;
  font-size: 9px;
  color: var(--color-gray-5);
  flex: none;
}
.gw-group-name {
  flex: 1;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gw-group-body {
  padding-left: 10px;
}
.gw-skill {
  display: block;
  padding: 3.5px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-sidebar-text);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0.85;
}
.gw-skill:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #fff;
  opacity: 1;
  text-decoration: none;
}
.gw-skill.active {
  background: var(--color-sidebar-active);
  color: #fff;
  font-weight: 600;
  opacity: 1;
  box-shadow: inset 2px 0 0 var(--color-sidebar-accent);
}
.gw-empty {
  font-size: 12px;
  color: var(--color-sidebar-text);
  opacity: 0.6;
  padding: var(--space-2);
  text-align: center;
}

/* 底部：用户信息 + 登出 */
.gw-tree-foot {
  margin-top: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.gw-user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 var(--space-1);
}
.gw-user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(139, 123, 243, 0.25);
  color: #c4b5fd;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.gw-user-name {
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gw-user-role {
  font-size: 10.5px;
  color: var(--color-sidebar-text);
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  padding: 1px 7px;
  flex: none;
}
.logout-btn {
  width: 100%;
  padding: 5px 0;
  background: transparent;
  color: var(--color-sidebar-text);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  transition: all var(--dur-fast) ease;
}
.logout-btn:hover {
  color: #ff8f93;
  border-color: rgba(229, 72, 77, 0.5);
  background: rgba(229, 72, 77, 0.08);
}
.gw-canvas {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: var(--space-4) var(--space-6);
}
</style>

/* 全局 toast（UI 批1） */
.sl-toasts {
  position: fixed;
  right: var(--space-4);
  bottom: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 1000;
}
.sl-toast {
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 13px;
  box-shadow: var(--shadow-md, 0 4px 12px rgba(0,0,0,.12));
  background: var(--color-surface);
  border-left: 3px solid var(--color-gray-4);
  max-width: 380px;
}
.sl-toast-ok { border-left-color: var(--color-success, #16a34a); }
.sl-toast-err { border-left-color: var(--color-danger, #dc2626); }

/* UI 批3：确认弹层 */
.sl-confirm-mask {
  position: fixed;
  inset: 0;
  background: rgba(17, 24, 39, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1100;
}
.sl-confirm {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: var(--space-4) var(--space-5);
  max-width: 380px;
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0,0,0,.18));
}
.sl-confirm p {
  margin: 0 0 var(--space-3);
  font-size: 14px;
}
.sl-confirm-btns {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
