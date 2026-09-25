import { createRouter, createWebHistory } from "vue-router";
import SkillsList from "./views/SkillsList.vue";
import SkillDetail from "./views/SkillDetail.vue";
import DeltaReport from "./views/DeltaReport.vue";
import ReplayLaunch from "./views/ReplayLaunch.vue";
import AuditView from "./views/AuditView.vue";
import CanvasView from "./views/CanvasView.vue";
import ReviewPortal from "./views/ReviewPortal.vue";

// 生产同源部署（FastAPI 托管 dist），API base 相对路径；路由五条（Task 2 三条 + Task 5 回放 + S10.5 审计）。
// S15：/reviews-portal 评审门户（夜间 agent_run 评审，区别于 Reports 四分类）。
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/skills" },
    { path: "/skills", name: "skills", component: SkillsList },
    { path: "/skills/:id", name: "skill-detail", component: SkillDetail },
    { path: "/reports/:deltaId", name: "delta-report", component: DeltaReport },
    { path: "/replay/:skillId", name: "replay-launch", component: ReplayLaunch },
    { path: "/audit", name: "audit", component: AuditView },
    { path: "/canvas", name: "canvas", component: CanvasView },
    { path: "/reviews-portal", name: "reviews-portal", component: ReviewPortal },
  ],
});

export default router;
