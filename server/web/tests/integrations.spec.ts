import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SkillDetail from "../src/views/SkillDetail.vue";
import DeltaReport from "../src/views/DeltaReport.vue";

// S25 块 W 前端：①SkillDetail 导出 Playwright 脚本按钮 ②DeltaReport 外部需求编号展示。

const card = {
  id: 3, name: "SaveForm", description: "d", status: "learned",
  confidence: 1.0, evidence_count: 1, alignment_id: 1,
  skeleton: [], input_variables: [], param_variables: [], assertions: [],
  last_run: null, window_params: {}, notes: "",
};

const report = {
  id: 1, expected_delta_id: 5, observed_delta_id: 6,
  expected: [], missing: [], unexpected: [], drift: [],
  created_at: "2026-09-27T12:00:00",
};

const expectedDeltaWithRef = {
  id: 5, requirement_id: "REQ-100", external_ref: "PROJ-123",
  feature: "保存", changes: [], status: "confirmed",
  reviewed_by: "alice", notes: "",
};

function loginAs(role: string): void {
  localStorage.setItem("sl_token", "tok");
  localStorage.setItem("sl_user", JSON.stringify({ id: 1, username: "a", role }));
}

function mockFetch(routes: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [prefix, body] of Object.entries(routes)) {
      if (url.includes(prefix)) {
        return new Response(JSON.stringify(body), {
          status: 200, headers: { "content-type": "application/json" } });
      }
    }
    return new Response("x", { status: 404 });
  });
}

async function mountView(root: HTMLElement, view: unknown, path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/run/:runId", component: { render: () => null } },
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/reports/:deltaId", component: { render: () => null } },
    ],
  });
  await router.push(path);
  const app = createApp({ render: () => h(view as never) });
  app.use(router);
  app.mount(root);
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("S25 integration UI", () => {
  it("SkillDetail shows export Playwright button", async () => {
    loginAs("admin");
    vi.stubGlobal("fetch", mockFetch({
      "/card": card, "/consistency": {}, "visual-baseline": { baseline: null },
      "locate-proposals": [],
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root, SkillDetail, "/graph/skill/3");
    for (let i = 0; i < 6; i++) await flush();
    expect(root.querySelector("[data-testid='export-playwright-btn']")
      ?.textContent).toContain("导出 Playwright 脚本");
  });

  it("DeltaReport shows external_ref when present, hides when null", async () => {
    loginAs("admin");
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/reports/1/perf": { baseline: { median: null, n: 0 },
                                  current_ms: null, history_ms: [] },
      "/api/v1/reports/1": report,
      "/api/v1/expected-deltas/5": expectedDeltaWithRef,
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root, DeltaReport, "/graph/reports/1");
    for (let i = 0; i < 6; i++) await flush();
    expect(root.querySelector("[data-testid='external-ref']")?.textContent)
      .toContain("PROJ-123");

    // external_ref 为 null → 不渲染
    document.body.innerHTML = "";
    const root2 = document.createElement("div");
    document.body.appendChild(root2);
    vi.stubGlobal("fetch", mockFetch({
      "/api/v1/reports/1/perf": { baseline: { median: null, n: 0 },
                                  current_ms: null, history_ms: [] },
      "/api/v1/reports/1": report,
      "/api/v1/expected-deltas/5": { ...expectedDeltaWithRef, external_ref: null },
    }));
    await mountView(root2, DeltaReport, "/graph/reports/1");
    for (let i = 0; i < 6; i++) await flush();
    expect(root2.querySelector("[data-testid='external-ref']")).toBeNull();
  });
});
