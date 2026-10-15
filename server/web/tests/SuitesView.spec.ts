import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SuitesView from "../src/views/SuitesView.vue";

// AR1：legacy 套件只读——无新建/执行/删除入口；迁移决策可见；历史可读。

const suites = [
  { id: 1, name: "冒烟分组", skill_ids: [5, 8],
    skills: [
      { id: 5, name: "SaveForm", status: "learned", system: "JeecG 表单" },
      { id: 8, name: "CreateRole", status: "learned", system: "Odoo 销售" },
    ],
    scenario_id: null,
    migration_status: "legacy_mixed_system",
    migration_reason: "混合系统套件：Odoo 销售、JeecG 表单",
    created_at: "2026-09-29T10:00:00" },
  { id: 2, name: "已映射分组", skill_ids: [5],
    skills: [{ id: 5, name: "SaveForm", status: "learned", system: "JeecG 表单" }],
    scenario_id: 17,
    migration_status: "reused",
    migration_reason: "有序 Skill 序列与简单场景完全一致",
    created_at: "2026-09-30T10:00:00" },
];

const history = [
  { id: 11, suite_id: 1, total: 2, pass_count: 1, fail_count: 0,
    error_count: 0, shadow_count: 1, results: [], created_at: "2026-09-29T11:00:00" },
];

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/v1/suites/1/runs") && method === "GET") {
      return new Response(JSON.stringify(history), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/suites") && method === "GET") {
      return new Response(JSON.stringify(suites), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountView(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/graph/suites", component: { render: () => null } },
      { path: "/graph/scenarios", component: { render: () => null } },
      { path: "/graph/skill/:id", component: { render: () => null } },
    ],
  });
  await router.push("/graph/suites");
  const app = createApp({ render: () => h(SuitesView) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("SuitesView（AR1 legacy 只读）", () => {
  it("renders migration decisions without write entry points", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    expect(root.textContent).toContain("冒烟分组");
    expect(root.textContent).toContain("legacy_mixed_system");
    expect(root.textContent).toContain("混合系统套件");
    expect(root.textContent).toContain("已映射场景 #17");
    expect(root.textContent).toContain("legacy");
    // 无新建/执行/删除入口
    expect(root.querySelector("[data-testid='suite-name']")).toBeNull();
    expect(root.querySelector("[data-testid='suite-create']")).toBeNull();
    expect(root.querySelector("[data-testid='suite-run-1']")).toBeNull();
    // 无任何写请求发出
    const writes = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method
        && (c[1] as RequestInit).method !== "GET");
    expect(writes.length).toBe(0);
  });

  it("shows run history for legacy suites", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    const btns = root.querySelectorAll(".suite-card .btn-secondary");
    (btns[0] as HTMLElement).click();
    await flush();
    await flush();

    const hist = root.querySelector("[data-testid='suite-history']");
    expect(hist).not.toBeNull();
    expect(hist?.textContent).toContain("通过 1 / 失败 0");
  });

  it("history load failure surfaces error without stale rows", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/suites/1/runs")) {
        return new Response(JSON.stringify({ detail: "db down" }), {
          status: 500, headers: { "content-type": "application/json" } });
      }
      if (url.includes("/api/v1/suites")) {
        return new Response(JSON.stringify(suites), {
          status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response("not found", { status: 404 });
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    const btns = root.querySelectorAll(".suite-card .btn-secondary");
    (btns[0] as HTMLElement).click();
    await flush();
    await flush();

    const hist = root.querySelector("[data-testid='suite-history']");
    expect(hist).not.toBeNull();
    expect(root.querySelector("[data-testid='history-error']")?.textContent)
      .toContain("加载失败");
    expect(hist?.querySelectorAll("tbody tr").length ?? 0).toBe(0);
  });
});
