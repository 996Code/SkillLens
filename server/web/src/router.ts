import { createRouter, createWebHistory } from "vue-router";
import DashboardView from "./views/DashboardView.vue";
import SkillsList from "./views/SkillsList.vue";
import SkillDetail from "./views/SkillDetail.vue";
import DeltaReport from "./views/DeltaReport.vue";
import ReplayLaunch from "./views/ReplayLaunch.vue";
import ReplayRunView from "./views/ReplayRunView.vue";
import AuditView from "./views/AuditView.vue";
import CanvasView from "./views/CanvasView.vue";
import ReviewPortal from "./views/ReviewPortal.vue";
import TimelineView from "./views/TimelineView.vue";
import SuitesView from "./views/SuitesView.vue";
import LoginView from "./views/LoginView.vue";
import { getToken } from "./api";

// 生产同源部署（FastAPI 托管 dist），API base 相对路径；路由八条（S21 增 /login）。
// S15：/reviews-portal 评审门户（夜间 agent_run 评审，区别于 Reports 四分类）。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/dashboard" },
    { path: "/login", name: "login", component: LoginView },
    { path: "/dashboard", name: "dashboard", component: DashboardView },
    { path: "/skills", name: "skills", component: SkillsList },
    { path: "/skills/:id", name: "skill-detail", component: SkillDetail },
    { path: "/reports/:deltaId", name: "delta-report", component: DeltaReport },
    { path: "/replay/:skillId", name: "replay-launch", component: ReplayLaunch },
    { path: "/replay-runs/:runId", name: "replay-run", component: ReplayRunView },
    { path: "/audit", name: "audit", component: AuditView },
    { path: "/canvas", name: "canvas", component: CanvasView },
    { path: "/reviews-portal", name: "reviews-portal", component: ReviewPortal },
    { path: "/timeline", name: "timeline", component: TimelineView },
    { path: "/suites", name: "suites", component: SuitesView },
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
