import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import DashboardView from "../src/views/DashboardView.vue";

// S28 块 Y 仪表盘测试：统计卡/趋势图/环形图/活动流渲染 + 空数据态。

const dashData = {
  skills: { total: 10, learned: 6, candidate: 4, generic_learned: 3 },
  replays: {
    total: 20, pass: 12, fail: 3, error: 2, shadow: 3, flaky: 1,
    recent: [
      { id: 1, skill_id: 8, skill_name: "ExecuteSearch", status: "pass",
        mode: "execute", flaky: false, duration_ms: 514, ts: "2026-09-28T10:00:00" },
      { id: 2, skill_id: 9, skill_name: "SaveForm", status: "fail",
        mode: "execute", flaky: true, duration_ms: 800, ts: "2026-09-28T09:00:00" },
    ],
  },
  reports: {
    total: 9,
    last: { id: 9, expected: 2, missing: 0, unexpected: 6, drift: 0,
            created_at: "2026-09-28T08:00:00" },
  },
  reviews_pending: 4,
  trend: Array.from({ length: 14 }, (_, i) => ({
    date: `2026-09-${String(i + 15).padStart(2, "0")}`,
    total: i % 3, pass: i % 3 === 0 ? 0 : 1,
  })),
};

function mockFetch(body: unknown) {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" } }));
}

async function mountDash(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/dashboard", component: { render: () => null } },
      { path: "/skills/:id", component: { render: () => null } },
    ],
  });
  await router.push("/dashboard");
  const app = createApp({ render: () => h(DashboardView) });
  app.use(router);
  app.mount(root);
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("DashboardView (S28)", () => {
  it("renders stat cards, trend, donut and activity", async () => {
    localStorage.setItem("sl_token", "t");
    vi.stubGlobal("fetch", mockFetch(dashData));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDash(root);
    for (let i = 0; i < 8; i++) await flush();

    // 统计卡：大数字
    const stats = root.querySelector("[data-testid='stat-row']")!;
    expect(stats.textContent).toContain("10");
    expect(stats.textContent).toContain("3");  // generic_learned
    expect(stats.textContent).toContain("flaky");

    // 趋势 SVG
    expect(root.querySelector("[data-testid='trend-block'] svg")).not.toBeNull();

    // 环形图 + 图例
    const donut = root.querySelector("[data-testid='donut-block']")!;
    expect(donut.querySelector("svg")).not.toBeNull();
    expect(donut.textContent).toContain("expected");
    expect(donut.textContent).toContain("6");

    // 活动流：最近回放含 flaky 徽标
    const activity = root.querySelector("[data-testid='activity-block']")!;
    expect(activity.textContent).toContain("ExecuteSearch");
    expect(activity.textContent).toContain("flaky");
  });

  it("renders empty states when no data", async () => {
    localStorage.setItem("sl_token", "t");
    vi.stubGlobal("fetch", mockFetch({
      skills: { total: 0, learned: 0, candidate: 0, generic_learned: 0 },
      replays: { total: 0, pass: 0, fail: 0, error: 0, shadow: 0, flaky: 0, recent: [] },
      reports: { total: 0, last: null },
      reviews_pending: 0,
      trend: [],
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDash(root);
    for (let i = 0; i < 8; i++) await flush();

    expect(root.textContent).toContain("暂无回放记录");
    expect(root.textContent).toContain("暂无报告");
  });
});
