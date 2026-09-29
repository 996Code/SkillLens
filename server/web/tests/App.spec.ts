import { describe, expect, it } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";

// vitest 起步用例：App 壳渲染顶部导航（Skills / Reports / 审计 / 画布 / 评审）——不依赖额外测试库。
// S15：导航加"评审"（/reviews-portal，夜间 agent_run 评审，区别于 Reports 四分类）。
function mountTo(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: { render: () => h("div") } }],
  });
  const app = createApp({ render: () => h(App) });
  app.use(router);
  app.mount(root);
  return app;
}

describe("App shell", () => {
  it("renders top nav links", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    mountTo(root);
    await Promise.resolve(); // 等一帧渲染

    const links = Array.from(root.querySelectorAll("nav a")).map(
      (a) => a.textContent?.trim(),
    );
    expect(links).toEqual(
      ["图工作台", "仪表盘", "操作流程", "Reports", "审计", "编排", "评审", "套件", "链路"]);
    expect(root.textContent).toContain("SkillLens");
    expect(root.querySelector("main")).not.toBeNull(); // router-view 出口存在
  });
});
