import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import ReplayLaunch from "../src/views/ReplayLaunch.vue";

// Task 5（S9 块C）测试：
// 门控 3 用例——shadow 默认可直接提交 / execute 未勾复选禁用 / 勾选后
// confirm_side_effect=true 随请求发出（C1 的 UI 化二要素）；
// 结果渲染 1 用例——pass 结果四区块（状态/断言明细/归因隐藏/前后快照对比）上屏。

const card = {
  id: 6, name: "SaveFormAndTableConfig", description: "d", status: "learned",
  confidence: 1.0, evidence_count: 2, alignment_id: 1,
  skeleton: [{ signature: "api|POST|/save" }],
  input_variables: [
    { name: "标题", values: { s1: "旧标题" } },
    { name: "备注", values: { s1: "旧备注" } },
  ],
  param_variables: [],
  assertions: [{ id: 1, kind: "api_status", layer: 3, payload: {} }],
  last_run: null, window_params: null, notes: "",
};

const observeOk = {
  id: 11, items: [], replay_run_id: 9, replay_status: "pass",
};

async function mountReplay(root: HTMLElement, path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/run/:runId", component: { render: () => null } },
      { path: "/", component: { render: () => null } },
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/replay/:skillId", component: { render: () => null } },
    ],
  });
  await router.push(path);
  const app = createApp({ render: () => h(ReplayLaunch) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

/** 填 delta id 并提交（jsdom 不实现按钮点击触发表单提交，直接派发 submit）。 */
async function submit(root: HTMLElement) {
  const deltaInput = root.querySelector(
    'input[aria-label="expected_delta_id"]') as HTMLInputElement;
  deltaInput.value = "5";
  deltaInput.dispatchEvent(new Event("input"));
  const form = root.querySelector("form.launch") as HTMLFormElement;
  form.dispatchEvent(new Event("submit", { cancelable: true }));
  await flush();
  await flush();
  await flush();
}

/** card 请求恒 mock；observe 的请求用可断言的 spy 返回。 */
function mockFetch(observeResp?: () => Response) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/v1/skills/6/card")) {
      return new Response(JSON.stringify(card), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/expected-deltas/5/observe")) {
      if (!observeResp) return new Response("x", { status: 500 });
      return observeResp();
    }
    if (url.includes("/api/v1/replay-runs/")) {
      return new Response(JSON.stringify(runDetail), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

const runDetail = {
  id: 9, skill_id: 6, mode: "execute", status: "pass",
  plan: {
    url: "http://x/",
    steps: [],
    before_snapshot: { phase: "before", ts: 1, forms: [
      { label: "标题", value: "旧标题" },
      { label: "备注", value: "旧备注" },
      { label: "状态", value: "草稿" },
    ], labels: [], tables: [] },
    after_snapshot: { phase: "after", ts: 2, forms: [
      { label: "标题", value: "新标题" },
      { label: "备注", value: "旧备注" },
      { label: "状态", value: "已提交" },
    ], labels: [], tables: [] },
  },
  executed: [],
  assertion_results: [
    { kind: "api_status",
      payload: { api_template: "/save", expect_status: 200 },
      observed_status: 200, passed: true },
    { kind: "ui_text",
      payload: { label: "状态", before: "草稿", after: "已提交" },
      observed_status: null, passed: true },
    { kind: "field_change",
      payload: { field: "x", before: "a", after: "b" },
      observed_status: null, passed: true, skipped: "field_change 不在回放中判定" },
  ],
  attribution: null, artifact_path: "",
};

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("ReplayLaunch 门控（C1 UI）", () => {
  it("shadow 默认选中且可直接提交（无需复选）", async () => {
    const fetchMock = mockFetch(() =>
      new Response(JSON.stringify(observeOk), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReplay(root, "/graph/replay/6");
    await flush();
    await flush();

    // 动态 overrides 行来自 input_variables
    expect(root.querySelectorAll(".override-row").length).toBe(2);
    const shadow = root.querySelector(
      "input[type=radio][value=shadow]") as HTMLInputElement;
    expect(shadow?.checked).toBe(true);
    // 无复选框、提交可点
    expect(root.querySelector("input[type=checkbox]")).toBeNull();
    const btn = root.querySelector(
      "form button[type=submit]") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);

    await submit(root);
    const call = fetchMock.mock.calls.find(([u]) =>
      String(u).includes("/observe"));
    expect(call).toBeTruthy();
    expect(JSON.parse(String(call![1]?.body))).toEqual({
      skill_id: 6, overrides: {}, confirm_side_effect: false,
    });
  });

  it("选 execute 未勾副作用复选 → 提交禁用", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReplay(root, "/graph/replay/6");
    await flush();
    await flush();

    const exec = root.querySelector(
      "input[type=radio][value=execute]") as HTMLInputElement;
    exec.click();
    await flush();
    const box = root.querySelector(
      "input[type=checkbox]") as HTMLInputElement;
    expect(box).not.toBeNull();
    const btn = root.querySelector(
      "form button[type=submit]") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("勾选后 confirm_side_effect=true 随 observe 请求发出", async () => {
    const fetchMock = mockFetch(() =>
      new Response(JSON.stringify(observeOk), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReplay(root, "/graph/replay/6");
    await flush();
    await flush();

    (root.querySelector("input[type=radio][value=execute]") as HTMLInputElement).click();
    await flush();
    // overrides 填一个值
    const inputs = root.querySelectorAll(".override-row input");
    (inputs[0] as HTMLInputElement).value = "新标题";
    (inputs[0] as HTMLInputElement).dispatchEvent(new Event("input"));
    (root.querySelector("input[type=checkbox]") as HTMLInputElement).click();
    await flush();
    const btn = root.querySelector(
      "form button[type=submit]") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);

    await submit(root);
    const call = fetchMock.mock.calls.find(([u]) =>
      String(u).includes("/observe"));
    expect(JSON.parse(String(call![1]?.body))).toEqual({
      skill_id: 6,
      overrides: { "标题": "新标题" },
      confirm_side_effect: true,
    });
  });
});

describe("ReplayLaunch 结果渲染", () => {
  it("pass 结果：状态/断言明细/快照对比上屏，归因区块隐藏", async () => {
    vi.stubGlobal("fetch", mockFetch(() =>
      new Response(JSON.stringify(observeOk), { status: 201 })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountReplay(root, "/graph/replay/6");
    await flush();
    await flush();
    await submit(root);
    await flush();

    // 区块 1：run 状态（pass 大字绿）
    const status = root.querySelector(".run-status");
    expect(status?.textContent?.trim()).toBe("pass");
    expect(status?.className).toContain("st-pass");
    expect(root.textContent).toContain("replay_run #9");
    // 区块 2：断言明细（3 行：kind/期望/观察/passed）
    const rows = root.querySelectorAll(".assert-tbl tbody tr");
    expect(rows.length).toBe(3);
    expect(root.textContent).toContain("/save → 200");
    expect(root.textContent).toContain("200");
    expect(root.textContent).toContain("field_change 不在回放中判定");
    // 区块 3：fail/error 才有归因 → pass 时无
    expect(root.querySelector(".attribution")).toBeNull();
    // 区块 4：前后快照对比——只显有差异行（标题/状态），备注（无差异）不显
    const diffRows = root.querySelectorAll(".diff-tbl tbody tr");
    expect(diffRows.length).toBe(2);
    expect(root.textContent).toContain("旧标题 → 新标题");
    expect(root.textContent).toContain("草稿 → 已提交");
    expect(root.textContent).not.toContain("旧备注 → 旧备注");
  });
});
