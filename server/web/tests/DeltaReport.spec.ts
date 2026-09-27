import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import DeltaReport from "../src/views/DeltaReport.vue";

// Task 4 测试：mock fetch 后四栏计数与首项 value 上屏。
const report = {
  id: 1,
  expected_delta_id: 5,
  observed_delta_id: 6,
  expected: [
    { type: "api_status", value: "/api/save: 200" },
    { type: "api_status", value: "/api/list: 200" },
  ],
  missing: [{ type: "ui_action", value: "点击[提交]" }],
  unexpected: [
    { type: "api_call", value: "DELETE /api/items/9" },
    { type: "api_call", value: "POST /api/audit" },
  ],
  drift: [{ type: "api_status", value: "/api/save: 200 -> 500" }],
  created_at: "2026-09-24T12:34:56",
};

const expectedDelta = {
  id: 5,
  requirement_id: "REQ-100",
  feature: "保存",
  changes: [{ type: "api_status", value: "/api/save: 200" }],
  status: "confirmed",
  reviewed_by: "alice",
  notes: "",
};

async function mountReport(root: HTMLElement, path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/reports/:deltaId", component: { render: () => null } },
    ],
  });
  await router.push(path);
  const app = createApp({ render: () => h(DeltaReport) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("DeltaReport", () => {
  it("renders four columns with counts and first item values", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/reports/1")) {
        return new Response(JSON.stringify(report), { status: 200 });
      }
      if (url.includes("/api/v1/expected-deltas/5")) {
        return new Response(JSON.stringify(expectedDelta), { status: 200 });
      }
      return new Response("x", { status: 404 });
    }));

    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    await flush();
    await flush();

    // 需求上下文
    expect(root.textContent).toContain("REQ-100");
    expect(root.textContent).toContain("alice");
    // 四栏计数
    const cols = root.querySelectorAll(".qcol");
    expect(cols.length).toBe(4);
    const counts = Array.from(root.querySelectorAll(".count")).map((c) =>
      c.textContent?.trim());
    expect(counts).toEqual(["2", "1", "2", "1"]);
    // 各栏类名（分色）
    expect(cols[0].className).toContain("col-expected");
    expect(cols[1].className).toContain("col-missing");
    expect(cols[2].className).toContain("col-unexpected");
    expect(cols[3].className).toContain("col-drift");
    // 首项 value 上屏
    expect(root.textContent).toContain("/api/save: 200");
    expect(root.textContent).toContain("点击[提交]");
    expect(root.textContent).toContain("DELETE /api/items/9");
    expect(root.textContent).toContain("/api/save: 200 -> 500");
    // type 徽标
    expect(root.querySelectorAll(".chip-type").length).toBeGreaterThanOrEqual(6);
    // footer 元数据
    expect(root.textContent).toContain("report #1");
    expect(root.textContent).toContain("2026-09-24 12:34:56");
  });

  it("renders query box (no list entry yet) on any state", async () => {
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    expect(root.querySelector(".query input")).not.toBeNull();
    expect(root.querySelector(".query button")).not.toBeNull();
  });

  it("renders not-found state for missing report", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 404 })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    await flush();
    expect(root.textContent).toContain("报告不存在");
  });

  // S12 Task 2（N2 先验对齐）：需求上下文区渲染"已发现实现"徽标与模板列表。
  it("renders linked discoveries badge in requirement context", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/reports/1")) {
        return new Response(JSON.stringify(report), { status: 200 });
      }
      if (url.includes("/api/v1/expected-deltas/5")) {
        return new Response(JSON.stringify(expectedDelta), { status: 200 });
      }
      if (url.includes("/api/v1/discoveries")) {
        return new Response(JSON.stringify([
          {
            id: 9,
            session_id: "s1",
            api_template: "/api/new-feature",
            anchor_label: null,
            observed_count: 2,
            status: "linked",
            linked_delta_id: 5,
            first_seen: "2026-09-25T10:00:00",
            last_seen: "2026-09-25T11:00:00",
          },
        ]), { status: 200 });
      }
      return new Response("x", { status: 404 });
    }));

    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    await flush();
    await flush();

    expect(root.textContent).toContain("已发现实现");
    expect(root.textContent).toContain("×1");
    expect(root.textContent).toContain("/api/new-feature");
  });
});

describe("DeltaReport perf block (S23)", () => {
  it("renders perf baseline and trend when perf context exists", async () => {
    const perfCtx = {
      baseline: { median: 1000, n: 3 },
      current_ms: 5000,
      history_ms: [900, 1000, 1100],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/reports/1/perf")) {
        return new Response(JSON.stringify(perfCtx), { status: 200 });
      }
      if (url.includes("/api/v1/reports/1")) {
        return new Response(JSON.stringify(report), { status: 200 });
      }
      if (url.includes("/api/v1/expected-deltas/5")) {
        return new Response(JSON.stringify(expectedDelta), { status: 200 });
      }
      return new Response("x", { status: 404 });
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    for (let i = 0; i < 6; i++) await flush();

    const block = root.querySelector("[data-testid='perf-block']");
    expect(block).not.toBeNull();
    expect(block?.textContent).toContain("1000ms");
    expect(block?.textContent).toContain("5000ms");
    // 趋势条：3 根历史 + 1 根当前
    expect(block?.querySelectorAll(".perf-bar").length).toBe(4);
  });

  it("hides perf block when perf endpoint 404 (old reports)", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/reports/1/perf")) {
        return new Response("x", { status: 404 });
      }
      if (url.includes("/api/v1/reports/1")) {
        return new Response(JSON.stringify(report), { status: 200 });
      }
      if (url.includes("/api/v1/expected-deltas/5")) {
        return new Response(JSON.stringify(expectedDelta), { status: 200 });
      }
      return new Response("x", { status: 404 });
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReport(root, "/reports/1");
    await flush();
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='perf-block']")).toBeNull();
    // 四分类仍正常渲染
    expect(root.textContent).toContain("REQ-100");
  });
});
