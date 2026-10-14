import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SkillGraphView from "../src/views/graph/SkillGraphView.vue";

// S42：SkillGraphView 合并了旧 SkillDetail 的详情面板——
// 断言表/自愈提案/视觉回归/导出按钮/路由参数切换重载（S41 修复回归）。

const card = {
  id: 3, name: "SaveForm", description: "保存表单", status: "learned",
  confidence: 1.0, evidence_count: 2, alignment_id: 1,
  skeleton: [{ signature: "action|input|请输入" }],
  input_variables: [], param_variables: [],
  assertions: [
    { id: 1, kind: "api_status", layer: 3,
      payload: { api_template: "/api/save", expect_status: 200 } },
    { id: 2, kind: "ui_text", layer: 2,
      payload: { label: "状态", before: "草稿", after: "已保存" } },
  ],
  last_run: { id: 9, status: "pass", mode: "execute", flaky: true,
              ts: "2026-09-27T10:00:00" },
  window_params: {}, notes: "",
};

const flow = { nodes: [], edges: [] };

const proposals = [
  { id: 1, skill_id: 3, step_label: "保存", proposed_label: "提交表单",
    strategy: "role-button", status: "promoted", verify_count: 3,
    source_run_id: 9, attribution: "按钮改名导致定位失败",
    created_at: "2026-09-27T09:00:00" },
  { id: 2, skill_id: 3, step_label: "搜索", proposed_label: "不存在的",
    strategy: "", status: "proposed", verify_count: 0,
    source_run_id: 9, attribution: null,
    created_at: "2026-09-27T09:30:00" },
];

function loginAs(role: "admin" | "reviewer" | "viewer"): void {
  localStorage.setItem("sl_token", "tok");
  localStorage.setItem("sl_user", JSON.stringify({ id: 1, username: "alice", role }));
}

function mockFetch(opts: { proposals?: typeof proposals; visual?: unknown } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/flow")) {
      return new Response(JSON.stringify(flow),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/runs")) {
      return new Response(JSON.stringify([
        { id: 9, skill_id: 3, status: "pass", mode: "execute",
          flaky: true, failure_class: null, duration_ms: 1234,
          created_at: "2026-09-27T10:00:00", steps: 2 },
      ]), { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("locate-proposals")) {
      return new Response(
        JSON.stringify(opts.proposals ?? proposals),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("visual-baseline")) {
      return new Response(
        JSON.stringify(opts.visual ?? { baseline: null, last_result: null }),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("consistency")) {
      return new Response(JSON.stringify({ runs: 0, consistent: true }),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify(card), {
      status: 200, headers: { "content-type": "application/json" } });
  });
}

async function mountView(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/skill/:skillId", name: "graph-skill",
        component: { render: () => null } },
      { path: "/graph/run/:runId", component: { render: () => null } },
      { path: "/graph/replay/:skillId", component: { render: () => null } },
    ],
  });
  await router.push("/graph/skill/3");
  const app = createApp({ render: () => h(SkillGraphView) });
  app.use(router);
  app.mount(root);
  return { app, router };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("SkillGraphView 详情面板（S42 合并）", () => {
  it("渲染断言表（kind/layer/期望摘要）", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 8; i++) await flush();

    expect(root.textContent).toContain("SaveForm");
    expect(root.textContent).toContain("api_status");
    expect(root.textContent).toContain("/api/save → 200");
    expect(root.textContent).toContain("状态: 草稿 → 已保存");
  });

  it("自愈提案区块：状态徽标/归因/flaky 徽标/reviewer 可否决", async () => {
    loginAs("reviewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 8; i++) await flush();

    const section = root.querySelector("[data-testid='proposal-section']")!;
    expect(section.textContent).toContain("保存");
    expect(section.textContent).toContain("提交表单");
    expect(section.textContent).toContain("promoted");
    // UI 批2：flaky 标记随 last_run 块升级进历史表（badge 内联 ·flaky）
    expect(root.querySelector("[data-testid='skill-run-history']")?.textContent)
      .toContain("flaky");
    expect(root.querySelector("[data-testid='reject-1']")).not.toBeNull();
  });

  it("viewer 角色无否决按钮", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 8; i++) await flush();

    expect(root.querySelector("[data-testid='proposal-section']")).not.toBeNull();
    expect(root.querySelector("[data-testid='reject-1']")).toBeNull();
  });

  it("无提案时区块隐藏；无基线时视觉回归空态", async () => {
    loginAs("admin");
    vi.stubGlobal("fetch", mockFetch({ proposals: [] }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 8; i++) await flush();

    expect(root.querySelector("[data-testid='proposal-section']")).toBeNull();
    expect(root.querySelector("[data-testid='visual-empty']")?.textContent)
      .toContain("未建立视觉基线");
  });

  it("导出 Playwright 按钮 + 回放入口存在", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 8; i++) await flush();

    expect(root.querySelector("[data-testid='export-playwright-btn']")).not.toBeNull();
    expect(root.querySelector("a[href='/graph/replay/3']")).not.toBeNull();
  });

  it("视觉回归：基线+比对失败（差异占比/两图并排/重置按钮）", async () => {
    loginAs("reviewer");
    const baseline = {
      skill_id: 3, file_path: "x/baseline.png", image_hash: "ab12",
      width: 1280, height: 720, source_run_id: 9,
      created_at: "2026-09-26T08:00:00",
    };
    const failResult = {
      run_id: 10, run_status: "fail", passed: false, ts: "2026-09-27T10:00:00",
      payload: { kind: "visual_baseline", passed: false, hash_distance: 28,
                 diff_ratio: 0.18, threshold: 0.02, size_changed: false,
                 error: null },
    };
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch({
      visual: { baseline, last_result: failResult },
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 10; i++) await flush();

    const section = root.querySelector("[data-testid='visual-section']")!;
    expect(section.textContent).toContain("视觉差异");
    expect(section.textContent).toContain("18.00%");
    expect(root.querySelector("[data-testid='visual-pair']")).not.toBeNull();
    expect(root.querySelector("[data-testid='visual-reset-btn']")).not.toBeNull();
  });

  it("卸载时 revoke 视觉基线 blob URL（评审#2 泄漏收口）", async () => {
    loginAs("reviewer");
    const baseline = {
      skill_id: 3, file_path: "x/baseline.png", image_hash: "ab12",
      width: 1280, height: 720, source_run_id: 9,
      created_at: "2026-09-26T08:00:00",
    };
    const revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
      revokeObjectURL: revoke,
    }));
    vi.stubGlobal("fetch", mockFetch({
      visual: { baseline, last_result: null },
    }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    const { app } = await mountView(root);
    for (let i = 0; i < 10; i++) await flush();

    app.unmount();
    expect(revoke).toHaveBeenCalledWith("blob:mock");
  });

  it("路由参数变化时重新加载（S41 修复回归）", async () => {
    loginAs("viewer");
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    const { router } = await mountView(root);
    for (let i = 0; i < 8; i++) await flush();
    const callsBefore = fetchMock.mock.calls.length;

    await router.push("/graph/skill/4");
    for (let i = 0; i < 8; i++) await flush();

    // 切换 skill 触发新一轮 card/flow 请求（不刷新整页）
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("/skills/4/");
  });
});
