import { createRouter, createWebHistory } from "vue-router";
import GraphWorkspace from "./views/graph/GraphWorkspace.vue";
import GraphOverview from "./views/graph/GraphOverview.vue";
import SkillGraphView from "./views/graph/SkillGraphView.vue";
import SuitesView from "./views/SuitesView.vue";
import TimelineView from "./views/TimelineView.vue";
import ReplayRunView from "./views/ReplayRunView.vue";
import ReplayLaunch from "./views/ReplayLaunch.vue";
import AuditView from "./views/AuditView.vue";
import CanvasView from "./views/CanvasView.vue";
import DeltaReport from "./views/DeltaReport.vue";
import ReviewPortal from "./views/ReviewPortal.vue";
import LoginView from "./views/LoginView.vue";
import { getToken } from "./api";

// S39b：统一路由——所有页面都在图工作台壳（GraphWorkspace）内，
// 左树是唯一导航。旧路由重定向到新路径（不丢深链）。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/graph" },
    { path: "/login", name: "login", component: LoginView },
    {
      path: "/graph",
      component: GraphWorkspace,
      children: [
        { path: "", name: "graph", component: GraphOverview },
        { path: "skill/:skillId", name: "graph-skill", component: SkillGraphView },
        { path: "suites", name: "suites", component: SuitesView },
        { path: "timeline", name: "timeline", component: TimelineView },
        { path: "run/:runId", name: "graph-run", component: ReplayRunView },
        { path: "replay/:skillId", name: "replay-launch", component: ReplayLaunch },
        { path: "audit", name: "audit", component: AuditView },
        { path: "canvas", name: "canvas", component: CanvasView },
        { path: "reports/:deltaId", name: "delta-report", component: DeltaReport },
        { path: "reviews-portal", name: "reviews-portal", component: ReviewPortal },
      ],
    },
    // 旧路由重定向（不丢深链）
    { path: "/dashboard", redirect: "/graph" },
    { path: "/skills", redirect: "/graph" },
    { path: "/skills/:id", redirect: (to) => `/graph/skill/${to.params.id}` },
    { path: "/replay-runs/:runId", redirect: (to) => `/graph/run/${to.params.runId}` },
    { path: "/replay/:skillId", redirect: (to) => `/graph/replay/${to.params.skillId}` },
    { path: "/reports/:deltaId", redirect: (to) => `/graph/reports/${to.params.deltaId}` },
    { path: "/audit", redirect: "/graph/audit" },
    { path: "/canvas", redirect: "/graph/canvas" },
    { path: "/reviews-portal", redirect: "/graph/reviews-portal" },
    { path: "/timeline", redirect: "/graph/timeline" },
    { path: "/suites", redirect: "/graph/suites" },
  ],
});

// S21 块 S：路由守卫——无 token 一律去 /login（登录页本身豁免）
router.beforeEach((to) => {
  if (to.path !== "/login" && !getToken()) {
    return { path: "/login" };
  }
  return true;
});

export default router;
