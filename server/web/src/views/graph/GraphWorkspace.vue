<script setup lang="ts">
// S40 图工作台壳 v2：左树=分组折叠+搜索+系统徽标；中=RouterView。
// 修复 S39 的"文字墙"问题：62 个流程不再平铺，按系统分组可折叠，
// 顶部搜索框实时过滤。
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { getSkills, listScenarios, listSuites, logout } from "../../api";
import type { SkillListItem, SuiteItem } from "../../api";
import { groupBySystem } from "../../system-group";
import { useToasts } from "../../toast";
import { useConfirmReq, answerConfirm } from "../../confirm";
const confirmReq = useConfirmReq();

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
const error = ref("");

const currentSkillId = computed(() =>
  route.name === "graph-skill" ? String(route.params.skillId) : "");

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
    <!-- 左：导航树（分组折叠+搜索） -->
    <aside class="gw-tree">
      <div class="gw-brand">SkillLens</div>

      <!-- 搜索框 -->
      <div class="gw-search">
        <input
          v-model="search"
          type="text"
          placeholder="搜索流程…"
          aria-label="搜索流程"
          data-testid="tree-search"
        />
      </div>

      <RouterLink to="/graph" class="gw-tree-root" data-testid="gw-overview-link">
        ◈ 系统总览
      </RouterLink>

      <!-- AQ2 四区导航：①测试场景（用户工作层——一等入口） -->
      <div class="gw-tree-group">测试场景</div>
      <RouterLink to="/graph/scenarios" class="gw-tree-leaf gw-nav-scenario"
                  data-testid="gw-scenarios-link">
        ⚡ 全部场景（{{ scenarioCount }}）
      </RouterLink>

      <!-- ②运行历史 -->
      <div class="gw-tree-group">运行历史</div>
      <RouterLink to="/graph/timeline" class="gw-tree-leaf">⌇ 时间线</RouterLink>
      <RouterLink to="/graph/failures" class="gw-tree-leaf">⚠ 失败分析</RouterLink>

      <!-- ③步骤库（技术层降级——默认收起） -->
      <div class="gw-tree-group">步骤库（{{ skills.length }}）</div>
      <button class="gw-group-head gw-lib-toggle" data-testid="gw-lib-toggle"
              @click="libraryCollapsed = !libraryCollapsed">
        <span class="gw-toggle">{{ libraryCollapsed ? "▸" : "▾" }}</span>
        <span class="gw-group-name">按系统浏览</span>
        <span class="gw-group-count">{{ skills.length }}</span>
      </button>
      <div v-show="!libraryCollapsed" class="gw-tree-scroll">
        <div v-for="[sys, list] in grouped" :key="sys" class="gw-group">
          <button class="gw-group-head" @click="toggleGroup(sys)">
            <span class="gw-toggle">{{ isCollapsed(sys) ? "▸" : "▾" }}</span>
            <span class="gw-group-name">{{ sys }}</span>
            <span class="gw-group-count">{{ list.length }}</span>
          </button>
          <div v-if="!isCollapsed(sys)" class="gw-group-body">
            <RouterLink
              v-for="s in list"
              :key="s.id"
              :to="`/graph/skill/${s.id}`"
              class="gw-tree-leaf"
              :class="{ active: currentSkillId === String(s.id) }"
              :data-testid="`gw-skill-${s.id}`"
            >
              {{ s.name }}
            </RouterLink>
          </div>
        </div>
        <p v-if="grouped.length === 0 && !loading" class="gw-empty">无匹配流程</p>
      </div>

      <!-- ④系统与环境 -->
      <div class="gw-tree-group">系统与环境</div>
      <RouterLink to="/graph/adapters" class="gw-tree-leaf">⚙ 系统接入</RouterLink>
      <RouterLink to="/graph/suites" class="gw-tree-leaf">▤ 流水线分组</RouterLink>

      <!-- 高级工具 -->
      <div class="gw-tree-group">高级工具</div>
      <RouterLink to="/graph/learning" class="gw-tree-leaf">↗ 学习图</RouterLink>
      <RouterLink to="/graph/canvas" class="gw-tree-leaf">✎ 编排画布</RouterLink>
      <RouterLink to="/graph/audit" class="gw-tree-leaf">⬡ 审计</RouterLink>
      <RouterLink to="/graph/reports" class="gw-tree-leaf">⌕ 报告</RouterLink>
      <RouterLink to="/graph/reviews-portal" class="gw-tree-leaf">✓ 评审</RouterLink>
      <RouterLink to="/graph/field-types" class="gw-tree-leaf">⌗ 字段类型</RouterLink>

      <div class="gw-tree-foot">
        <button class="logout-btn" data-testid="logout-btn" @click="doLogout">
          登出
        </button>
        <div class="tagline">变更智能工作台</div>
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
  width: 244px;
  flex-shrink: 0;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  background: var(--color-sidebar);
  overflow-y: auto;
  padding: var(--space-3) var(--space-2) var(--space-2);
  display: flex;
  flex-direction: column;
}
.gw-brand {
  font-weight: 800;
  font-size: 16px;
  letter-spacing: -0.01em;
  color: #fff;
  padding: var(--space-2) var(--space-2) var(--space-3);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  margin-bottom: var(--space-2);
  display: flex;
  align-items: center;
  gap: 8px;
}
.gw-brand::before {
  content: "";
  width: 22px;
  height: 22px;
  border-radius: 6px;
  background: linear-gradient(135deg, var(--color-primary) 0%,
    var(--color-sidebar-accent) 100%);
  box-shadow: 0 2px 8px rgba(109, 90, 230, 0.45);
  flex: none;
}
.gw-search {
  padding: var(--space-1) var(--space-1) var(--space-2);
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
}
.gw-search input:focus {
  outline: none;
  border-color: var(--color-sidebar-accent);
  box-shadow: 0 0 0 3px rgba(139, 123, 243, 0.18);
}
.gw-tree-root {
  display: block;
  padding: 7px var(--space-2);
  border-radius: var(--radius-md);
  font-size: 13.5px;
  font-weight: 600;
  color: #fff;
  text-decoration: none;
}
.gw-tree-root:hover {
  background: var(--color-sidebar-hover);
  text-decoration: none;
}
.gw-tree-root.router-link-active {
  background: var(--color-sidebar-active);
  box-shadow: inset 2px 0 0 var(--color-sidebar-accent);
  color: #fff;
}
.gw-tree-group {
  font-size: 10.5px;
  color: var(--color-sidebar-text);
  opacity: 0.7;
  padding: var(--space-3) var(--space-2) var(--space-1);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.gw-tree-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.gw-group {
  margin-bottom: 2px;
}
.gw-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 5px var(--space-2);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: 12px;
  font-weight: 600;
  color: var(--color-sidebar-text);
  cursor: pointer;
}
.gw-group-head:hover {
  background: var(--color-sidebar-hover);
  color: #fff;
}
.gw-toggle {
  width: 14px;
  font-size: 10px;
  color: var(--color-gray-5);
}
.gw-group-name {
  flex: 1;
  text-align: left;
}
.gw-group-count {
  font-size: 10px;
  color: var(--color-sidebar-text);
  background: rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  padding: 1px 6px;
}
.gw-group-body {
  padding-left: 14px;
}
.gw-tree-leaf {
  display: block;
  padding: 4px var(--space-2);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--color-sidebar-text);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  transition: background var(--dur-fast) ease, color var(--dur-fast) ease;
}
.gw-tree-leaf:hover {
  background: var(--color-sidebar-hover);
  color: #fff;
  text-decoration: none;
}
.gw-tree-leaf.active,
.gw-tree-leaf.router-link-active {
  background: var(--color-sidebar-active);
  color: var(--color-sidebar-text-active);
  font-weight: 600;
  box-shadow: inset 2px 0 0 var(--color-sidebar-accent);
}
.gw-empty {
  font-size: 12px;
  color: var(--color-sidebar-text);
  opacity: 0.6;
  padding: var(--space-2);
  text-align: center;
}
.gw-tree-foot {
  margin-top: auto;
  padding: var(--space-2);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.logout-btn {
  width: 100%;
  padding: 5px 0;
  background: transparent;
  color: var(--color-sidebar-text);
  border: 1px solid rgba(255, 255, 255, 0.14);
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
.tagline {
  font-size: 10px;
  color: var(--color-sidebar-text);
  opacity: 0.5;
  text-align: center;
  margin-top: var(--space-1);
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

/* AQ2：场景一级入口强调 */
.gw-nav-scenario {
  font-weight: 650;
  color: var(--color-sidebar-text-active);
  background: rgba(139, 123, 243, 0.14);
  border: 1px solid rgba(139, 123, 243, 0.25);
  margin: 0 var(--space-1) var(--space-2);
  padding: 6px var(--space-2);
  border-radius: var(--radius-md);
}
.gw-nav-scenario:hover {
  background: rgba(139, 123, 243, 0.22);
}
.gw-lib-toggle {
  margin: 0 var(--space-1) var(--space-1);
  width: calc(100% - 8px);
}
