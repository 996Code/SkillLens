import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SuitesView from "../src/views/SuitesView.vue";

// S37-3 测试套件：①列表渲染（含操作流程概要）②新建（勾选+创建）
// ③一键执行汇总（结果表+run 链接）④执行历史。
// 挂载方式同 TimelineView.spec.ts；fetch mock 按 URL 路由。

const skills = [
  { id: 5, name: "SaveForm", status: "learned", confidence: 0.9 },
  { id: 8, name: "CreateRole", status: "learned", confidence: 0.6 },
];

const suites = [
  { id: 1, name: "冒烟套件", skill_ids: [5, 8],
    skills: [
      { id: 5, name: "SaveForm", status: "learned" },
      { id: 8, name: "CreateRole", status: "learned" },
    ],
    created_at: "2026-09-29T10:00:00" },
];

const runSummary = {
  id: 11, suite_id: 1, total: 2,
  pass_count: 1, fail_count: 0, error_count: 0, shadow_count: 1,
  results: [
    { skill_id: 5, skill_name: "SaveForm", run_id: 190, status: "pass", mode: "execute" },
    { skill_id: 8, skill_name: "CreateRole", run_id: 191, status: "shadow", mode: "shadow" },
  ],
  created_at: "2026-09-29T11:00:00",
};

const history = [runSummary];

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/v1/skills") && method === "GET") {
      return new Response(JSON.stringify(skills), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/suites/1/runs") && method === "GET") {
      return new Response(JSON.stringify(history), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/suites/1/run") && method === "POST") {
      return new Response(JSON.stringify(runSummary), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/suites") && method === "GET") {
      return new Response(JSON.stringify(suites), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/suites") && method === "POST") {
      return new Response(JSON.stringify(suites[0]), {
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
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/run/:runId", component: { render: () => null } },
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

describe("SuitesView", () => {
  it("renders suites with skill briefs", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    expect(root.textContent).toContain("冒烟套件");
    expect(root.textContent).toContain("2 个操作流程");
    expect(root.textContent).toContain("SaveForm");
    // 操作流程选择器（新建区）
    expect(root.querySelectorAll(".pick-row").length).toBe(2);
  });

  it("creates suite from checked skills", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    (root.querySelector("[data-testid='suite-name']") as HTMLInputElement).value = "回归套件";
    (root.querySelector("[data-testid='suite-name']") as HTMLInputElement)
      .dispatchEvent(new Event("input"));
    // 勾选第一个 skill
    (root.querySelector(".pick-row input") as HTMLElement).click();
    await flush();
    (root.querySelector("[data-testid='suite-create']") as HTMLElement).click();
    await flush();
    await flush();

    const post = fetchMock.mock.calls
      .filter((c) => String(c[0]).includes("/api/v1/suites") && (c[1] as RequestInit)?.method === "POST")
      .map((c) => JSON.parse(String((c[1] as RequestInit).body)));
    expect(post.length).toBe(1);
    expect(post[0].name).toBe("回归套件");
    expect(post[0].skill_ids).toEqual([5]);
  });

  it("runs suite and shows summary with run links", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    (root.querySelector("[data-testid='suite-run-1']") as HTMLElement).click();
    await flush();
    await flush();

    const summary = root.querySelector("[data-testid='suite-run-summary']");
    expect(summary).not.toBeNull();
    expect(summary?.textContent).toContain("通过 1");
    expect(summary?.textContent).toContain("预演 1");
    const link = summary?.querySelector<HTMLAnchorElement>("a[href='/graph/run/190']");
    expect(link?.textContent).toContain("run #190");
  });

  it("shows run history", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    // 点执行历史按钮（suite-card 内的 secondary 按钮）
    const btns = root.querySelectorAll(".suite-card .btn-secondary");
    (btns[0] as HTMLElement).click();
    await flush();
    await flush();

    const hist = root.querySelector("[data-testid='suite-history']");
    expect(hist).not.toBeNull();
    expect(hist?.textContent).toContain("通过 1 / 失败 0");
  });
});
