import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SkillDetail from "../src/views/SkillDetail.vue";

// S22 块 T 前端测试：SkillDetail 视觉回归区块——
// ①无基线空态 ②基线+比对失败（差异占比/两图并排/重置按钮）③viewer 无重置按钮。
// fetch mock 按 URL 分流；图片走 blob → URL.createObjectURL（jsdom 需 stub）。

const card = {
  id: 3, name: "SaveForm", description: "保存表单", status: "learned",
  confidence: 1.0, evidence_count: 2, alignment_id: 1,
  skeleton: [{ signature: "action|input|请输入" }],
  input_variables: [], param_variables: [], assertions: [],
  last_run: { id: 9, status: "fail", mode: "execute", ts: "2026-09-27T10:00:00" },
  window_params: {}, notes: "",
};

const baselineInfo = {
  skill_id: 3, file_path: "x/baseline.png", image_hash: "ab12",
  width: 1280, height: 720, source_run_id: 9,
  created_at: "2026-09-26T08:00:00",
};

const failResult = {
  run_id: 10, run_status: "fail", passed: false, ts: "2026-09-27T10:00:00",
  payload: {
    kind: "visual_baseline", passed: false, hash_distance: 28,
    diff_ratio: 0.18, threshold: 0.02, size_changed: false, error: null,
  },
};

function loginAs(role: "admin" | "reviewer" | "viewer"): void {
  localStorage.setItem("sl_token", "tok");
  localStorage.setItem("sl_user", JSON.stringify({ id: 1, username: "alice", role }));
}

function mockFetch(visualBody: unknown) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("visual-baseline/image")) {
      return new Response(new Blob(["png"], { type: "image/png" }), { status: 200 });
    }
    if (url.includes("visual-baseline")) {
      return new Response(JSON.stringify(visualBody), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/card") || url.includes("/consistency")) {
      return new Response(JSON.stringify(card), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
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

describe("SkillDetail visual section (S22)", () => {
  it("shows empty state when no baseline", async () => {
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch({ baseline: null, last_result: null }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='visual-empty']")?.textContent)
      .toContain("未建立视觉基线");
    expect(root.querySelector("[data-testid='visual-pair']")).toBeNull();
  });

  it("renders diff stats, side-by-side images and reset for reviewer", async () => {
    loginAs("reviewer");
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch(
      { baseline: baselineInfo, last_result: failResult }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    await flush();
    await flush();

    const section = root.querySelector("[data-testid='visual-section']")!;
    expect(section.textContent).toContain("视觉差异");
    expect(section.textContent).toContain("18.00%");
    expect(section.textContent).toContain("28");
    const pair = root.querySelector("[data-testid='visual-pair']")!;
    expect(pair.querySelectorAll("img").length).toBe(2); // 基线 + 最近回放
    expect(root.querySelector("[data-testid='visual-reset-btn']")).not.toBeNull();
  });

  it("hides reset button for viewer role", async () => {
    loginAs("viewer");
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch(
      { baseline: baselineInfo, last_result: failResult }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountDetail(root);
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='visual-reset-btn']")).toBeNull();
  });
});
