import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import ReviewPortal from "../src/views/ReviewPortal.vue";

// AR1：评审门户只读——队列/已评审可看，无提交表单。

const pendingRuns = [
  { id: 3, graph_name: "canvas:2", status: "finished",
    started_at: "2026-09-29T08:56:16",
    node_outputs: [
      { node: "review_output", output: { review: "# 夜间回归摘要\n- 全绿" } },
    ] },
];

const reviews = [
  { id: 1, agent_run_id: 1, reviewer: "历史评审人", user_id: 1,
    decision: "approved", comment: "放行", created_at: "2026-09-28T09:00:00",
    agent_run: { graph_name: "nightly", status: "finished",
                 started_at: "2026-09-28T08:00:00" } },
];

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/v1/reviews/pending") && method === "GET") {
      return new Response(JSON.stringify(pendingRuns), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/reviews") && method === "GET") {
      return new Response(JSON.stringify(reviews), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountView(root: HTMLElement) {
  const app = createApp({ render: () => h(ReviewPortal) });
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("ReviewPortal（AR1 只读）", () => {
  it("renders pending queue and reviewed history without submit form", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    expect(root.textContent).toContain("canvas:2");
    expect(root.textContent).toContain("历史评审人");
    expect(root.textContent).toContain("通过");
    // 表单与提交入口不存在
    expect(root.querySelector("[data-testid='review-form']")).toBeNull();
    expect(root.querySelector("[data-testid='submit-btn']")).toBeNull();
    // 只读：零写请求
    const writes = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method
        && (c[1] as RequestInit).method !== "GET");
    expect(writes.length).toBe(0);
  });

  it("expands row to show markdown and frozen notice", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    (root.querySelector("[data-testid='pending-row']") as HTMLElement).click();
    await flush();

    expect(root.querySelector("[data-testid='review-markdown']")?.textContent)
      .toContain("夜间回归摘要");
    expect(root.querySelector("[data-testid='frozen-hint']")?.textContent)
      .toContain("AR4");
  });
});
