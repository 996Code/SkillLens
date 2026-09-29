import { describe, expect, it } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";

// S39b：App 壳极简化——无侧栏（GraphWorkspace 左树=唯一导航）。
// 登录页独立渲染；其余路由渲染 RouterView。
function mountTo(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/run/:runId", component: { render: () => null } },{ path: "/:pathMatch(.*)*", component: { render: () => h("div") } }],
  });
  const app = createApp({ render: () => h(App) });
  app.use(router);
  app.mount(root);
  return app;
}

describe("App shell (S39b unified)", () => {
  it("renders RouterView without sidebar", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    mountTo(root);
    await Promise.resolve();

    // 无旧侧栏（导航在 GraphWorkspace 左树）
    expect(root.querySelector(".sidebar")).toBeNull();
    // RouterView 出口存在
    expect(root.querySelector("main") || root.firstChild).not.toBeNull();
  });
});
