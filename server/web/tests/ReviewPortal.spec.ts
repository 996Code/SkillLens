import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import ReviewPortal from "../src/views/ReviewPortal.vue";

// S15 Task 3 评审门户测试：①队列渲染（pending 2 条，含 review_output 摘要标记）
// ②行点击展开表单 + 提交 body 断言（agent_run_id/reviewer/decision/comment）
// ③提交后队列刷新（已评运行从队列消失、进已评审列表）④已评审徽标（绿/红/橙）
// ⑤空态（夜间无待评审运行）。挂载方式同 CanvasView.spec.ts：createApp +
// memory router；fetch mock 按 URL+method 路由（POST 后状态可变）。

const pendingSeed = [
  {
    id: 11, graph_name: "canvas:7", status: "finished",
    started_at: "2026-09-28T02:00:00",
    node_outputs: [
      { node: "select_skills", output: { skills: [5] } },
      { node: "review_output", output: { review: "# 夜间回归摘要\n- 全绿" } },
    ],
  },
  {
    id: 12, graph_name: "nightly", status: "error",
    started_at: "2026-09-28T03:00:00", node_outputs: [],
  },
];

const reviewedSeed = [
  {
    id: 3, agent_run_id: 9, reviewer: "bob", decision: "approved",
    comment: "放行", created_at: "2026-09-27T09:00:00",
    agent_run: { graph_name: "nightly", status: "finished",
      started_at: "2026-09-27T02:00:00" },
  },
];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  });
}

/** 状态可变 fetch mock：POST /reviews 成功后，pending 少一条、reviews 多一条。 */
function mockReviewFetch(pending = pendingSeed.map((p) => ({ ...p })),
                         reviews = reviewedSeed.map((r) => ({ ...r }))) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (method === "POST" && url.endsWith("/api/v1/reviews")) {
      const body = JSON.parse((init?.body as string) || "{}");
      const run = pending.find((p) => p.id === body.agent_run_id);
      if (!run) return jsonResp({ detail: "agent_run not found" }, 404);
      pending.splice(pending.indexOf(run), 1);
      const row = {
        id: 9, agent_run_id: run.id, reviewer: "alice",
        decision: body.decision, comment: body.comment ?? null,
        created_at: "2026-09-28T08:00:00",
        agent_run: { graph_name: run.graph_name, status: run.status,
          started_at: run.started_at },
      };
      reviews.unshift(row);
      return jsonResp(row, 201);
    }
    if (url.includes("/api/v1/reviews/pending")) {
      return jsonResp(pending.map(({ node_outputs, ...rest }) =>
        ({ ...rest, node_outputs: node_outputs.map((s) => ({ ...s })) })));
    }
    if (url.includes("/api/v1/reviews")) {
      return jsonResp(reviews.map((r) => ({ ...r })));
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountPortal(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/run/:runId", component: { render: () => null } },
      { path: "/", component: { render: () => null } },
      { path: "/graph/reviews-portal", component: { render: () => null } },
    ],
  });
  await router.push("/graph/reviews-portal");
  const app = createApp({ render: () => h(ReviewPortal) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

function click(el: Element): void {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function setInput(el: HTMLInputElement | HTMLTextAreaElement, v: string): void {
  el.value = v;
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function checkRadio(el: HTMLInputElement): void {
  el.checked = true;
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function pendingRows(root: HTMLElement): Element[] {
  return Array.from(root.querySelectorAll("[data-testid='pending-row']"));
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

/** S21 块 S：评审人从登录态取——测试前注入会话用户。 */
function loginAs(role: "admin" | "reviewer" | "viewer"): void {
  localStorage.setItem("sl_token", "test-token");
  localStorage.setItem("sl_user", JSON.stringify(
    { id: 1, username: "alice", role }));
}

describe("ReviewPortal", () => {
  it("renders pending queue with run meta and review-summary mark", async () => {
    vi.stubGlobal("fetch", mockReviewFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    const rows = pendingRows(root);
    expect(rows.length).toBe(2);
    expect(rows[0]?.getAttribute("data-id")).toBe("11");
    expect(rows[0]?.textContent).toContain("canvas:7");
    expect(rows[0]?.textContent).toContain("finished");
    expect(rows[1]?.textContent).toContain("nightly");
    // review_output 段存在 → 摘要标记；无 → 占位
    expect(rows[0]?.querySelector("[data-testid='has-review']")).not.toBeNull();
    expect(rows[1]?.querySelector("[data-testid='has-review']")).toBeNull();
  });

  it("expands form on row click and submits review body", async () => {
    loginAs("reviewer");
    vi.stubGlobal("fetch", mockReviewFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    // 未展开时无表单；点击行 → 摘要 markdown + 表单
    expect(root.querySelector("[data-testid='review-form']")).toBeNull();
    click(pendingRows(root)[0]!);
    await flush();
    expect(root.querySelector("[data-testid='review-markdown']")?.textContent)
      .toContain("# 夜间回归摘要");
    expect(root.querySelector("[data-testid='review-form']")).not.toBeNull();

    checkRadio(root.querySelector(
      "[data-testid='decision-changes_requested']") as HTMLInputElement);
    setInput(
      root.querySelector("[data-testid='comment-input']") as HTMLTextAreaElement,
      "断言覆盖不足，打回补充");
    (root.querySelector("[data-testid='submit-btn']") as Element).click();
    await flush();
    await flush();

    const post = (vi.mocked(fetch) as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => [String(c[0]), c[1] as RequestInit | undefined])
      .find(([u, init]) =>
        u.endsWith("/api/v1/reviews") &&
        (init?.method || "GET").toUpperCase() === "POST");
    expect(post).toBeDefined();
    const body = JSON.parse(post![1]!.body as string);
    expect(body).toEqual({
      agent_run_id: 11,
      decision: "changes_requested",
      comment: "断言覆盖不足，打回补充",
    });
  });

  it("refreshes queue and reviewed list after submit", async () => {
    loginAs("reviewer");
    vi.stubGlobal("fetch", mockReviewFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    expect(pendingRows(root).length).toBe(2);

    click(pendingRows(root)[0]!); // 展开 #11
    await flush();
    checkRadio(root.querySelector(
      "[data-testid='decision-approved']") as HTMLInputElement);
    (root.querySelector("[data-testid='submit-btn']") as Element).click();
    await flush();
    await flush();

    // 已评运行从队列消失；表单收起；成功提示
    expect(pendingRows(root).length).toBe(1);
    expect(pendingRows(root)[0]?.getAttribute("data-id")).toBe("12");
    expect(root.querySelector("[data-testid='review-form']")).toBeNull();
    expect(root.querySelector("[data-testid='submit-hint']")?.textContent)
      .toContain("已提交");

    // 已评审列表刷新出新评审（alice / 通过）
    const reviewed = root.querySelector("[data-testid='reviewed-table']")!;
    expect(reviewed.textContent).toContain("alice");
    expect(reviewed.textContent).toContain("通过");
  });

  it("renders reviewed list with decision badges", async () => {
    vi.stubGlobal("fetch", mockReviewFetch(pendingSeed.map((p) => ({ ...p })), [
      { ...reviewedSeed[0]!, decision: "approved", comment: "放行" },
      { ...reviewedSeed[0]!, id: 2, decision: "rejected", comment: "回滚" },
      { ...reviewedSeed[0]!, id: 1, decision: "changes_requested",
        comment: "补断言" },
    ]));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    const badges = Array.from(
      root.querySelectorAll("[data-testid='decision-badge']"));
    expect(badges.length).toBe(3);
    expect(badges[0]?.getAttribute("class")).toContain("badge-approved");
    expect(badges[0]?.textContent).toContain("通过");
    expect(badges[1]?.getAttribute("class")).toContain("badge-rejected");
    expect(badges[1]?.textContent).toContain("驳回");
    expect(badges[2]?.getAttribute("class")).toContain("badge-changes_requested");
    expect(badges[2]?.textContent).toContain("打回");
    // 评语上屏
    expect(root.querySelector("[data-testid='reviewed-table']")?.textContent)
      .toContain("回滚");
  });

  it("shows empty state when no pending runs", async () => {
    vi.stubGlobal("fetch", mockReviewFetch([], []));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='pending-empty']")?.textContent)
      .toContain("夜间无待评审运行");
    expect(pendingRows(root).length).toBe(0);
  });
});

describe("ReviewPortal S21 viewer role", () => {
  it("hides review form and shows viewer hint for viewer role", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockReviewFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountPortal(root);
    await flush();
    await flush();

    click(pendingRows(root)[0]!);
    await flush();
    // viewer 只读：无表单，显示无权限提示
    expect(root.querySelector("[data-testid='review-form']")).toBeNull();
    expect(root.querySelector("[data-testid='viewer-hint']")).not.toBeNull();
    expect(root.querySelector("[data-testid='viewer-hint']")?.textContent)
      .toContain("只读");
  });
});
