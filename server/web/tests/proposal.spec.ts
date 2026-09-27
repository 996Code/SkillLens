import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SkillDetail from "../src/views/SkillDetail.vue";

// S24 块 U 前端测试：SkillDetail 自愈提案区块 + flaky 徽标。
// ①提案列表渲染（原标签→提案标签/状态徽标/归因摘要）②viewer 无否决按钮
// ③flaky 徽标（last_run.flaky）④无提案时区块隐藏。

const card = {
  id: 3, name: "SaveForm", description: "保存表单", status: "learned",
  confidence: 1.0, evidence_count: 2, alignment_id: 1,
  skeleton: [{ signature: "action|input|请输入" }],
  input_variables: [], param_variables: [], assertions: [],
  last_run: { id: 9, status: "pass", mode: "execute", flaky: true,
              ts: "2026-09-27T10:00:00" },
  window_params: {}, notes: "",
};

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

function mockFetch(withProposals = true) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("locate-proposals")) {
      return new Response(
        JSON.stringify(withProposals ? proposals : []),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("visual-baseline")) {
      return new Response(JSON.stringify({ baseline: null, last_result: null }),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify(card), {
      status: 200, headers: { "content-type": "application/json" } });
  });
}

async function mountDetail(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/skills/:id", component: { render: () => null } }],
  });
  await router.push("/skills/3");
  const app = createApp({ render: () => h(SkillDetail) });
  app.use(router);
  app.mount(root);
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("SkillDetail self-healing section (S24)", () => {
  it("renders proposals with status badges and attribution", async () => {
    loginAs("reviewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    for (let i = 0; i < 6; i++) await flush();

    const section = root.querySelector("[data-testid='proposal-section']")!;
    expect(section.textContent).toContain("保存");
    expect(section.textContent).toContain("提交表单");
    expect(section.textContent).toContain("promoted");
    expect(section.textContent).toContain("按钮改名导致定位失败".slice(0, 10));
    // flaky 徽标（last_run.flaky）
    expect(root.querySelector("[data-testid='flaky-badge']")?.textContent)
      .toContain("flaky");
    // reviewer 可否决（未否决的提案）
    expect(root.querySelector("[data-testid='reject-1']")).not.toBeNull();
  });

  it("hides reject buttons for viewer role", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    for (let i = 0; i < 6; i++) await flush();

    expect(root.querySelector("[data-testid='proposal-section']")).not.toBeNull();
    expect(root.querySelector("[data-testid='reject-1']")).toBeNull();
  });

  it("hides proposal section when none exist", async () => {
    loginAs("admin");
    vi.stubGlobal("fetch", mockFetch(false));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    for (let i = 0; i < 6; i++) await flush();

    expect(root.querySelector("[data-testid='proposal-section']")).toBeNull();
  });
});
