import { describe, expect, it } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import App from "../src/App.vue";

// vitest 起步用例：App 壳渲染顶部导航（Skills / Reports）——不依赖额外测试库。
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
    expect(links).toEqual(["Skills", "Reports"]);
    expect(root.textContent).toContain("SkillLens");
    expect(root.querySelector("main")).not.toBeNull(); // router-view 出口存在
  });
});
