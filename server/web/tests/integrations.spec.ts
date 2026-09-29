import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import DeltaReport from "../src/views/DeltaReport.vue";

// S25 块 W 前端：DeltaReport 外部需求编号展示。
// （SkillDetail 导出按钮用例已随 S42 合并迁至 graph-skill.spec.ts）

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

async function mountView(root: HTMLElement, path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/reports/:deltaId", component: { render: () => null } },
    ],
  });
  await router.push(path);
  const app = createApp({ render: () => h(DeltaReport) });
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
    await mountView(root, "/graph/reports/1");
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
    await mountView(root2, "/graph/reports/1");
    for (let i = 0; i < 6; i++) await flush();
    expect(root2.querySelector("[data-testid='external-ref']")).toBeNull();
  });
});
