import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import FieldTypesView from "../src/views/FieldTypesView.vue";

// S42-7：字段类型知识库维护页——列表渲染/新建/编辑/删除/权限。

const rows = [
  { id: 1, label_pattern: "请输入手机号码", field_type: "phone",
    example_value: "13899998888", source: "learned", source_skill_id: 7,
    success_count: 3, created_at: "2026-09-30T10:00:00" },
  { id: 2, label_pattern: "微信", field_type: "phone", example_value: "",
    source: "manual", source_skill_id: null, success_count: 0,
    created_at: "2026-09-30T11:00:00" },
];

function loginAs(role: string): void {
  localStorage.setItem("sl_token", "tok");
  localStorage.setItem("sl_user", JSON.stringify({ id: 1, username: "a", role }));
}

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/v1/field-types") && (init?.method ?? "GET") === "GET") {
      return new Response(JSON.stringify({ items: rows, builtin_types: ["phone", "email", "date"] }),
        { status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response(JSON.stringify({ id: 9, label_pattern: "x", field_type: "phone",
      example_value: "", source: "manual", source_skill_id: null, success_count: 0,
      created_at: "2026-09-30T12:00:00" }),
      { status: 200, headers: { "content-type": "application/json" } });
  });
}

async function mountView(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/graph/field-types", component: { render: () => null } }],
  });
  await router.push("/graph/field-types");
  const app = createApp({ render: () => h(FieldTypesView) });
  app.use(router);
  app.mount(root);
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("FieldTypesView（S42-7）", () => {
  it("渲染规则列表：来源徽标/成功计数/来源 skill", async () => {
    loginAs("admin");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 6; i++) await flush();

    expect(root.querySelector("[data-testid='ft-row-1']")?.textContent)
      .toContain("请输入手机号码");
    expect(root.querySelector("[data-testid='ft-row-1']")?.textContent)
      .toContain("learned");
    expect(root.querySelector("[data-testid='ft-row-1']")?.textContent)
      .toContain("skill #7");
    expect(root.querySelector("[data-testid='ft-row-1']")?.textContent)
      .toContain("3");
  });

  it("admin 可见新建区并可提交", async () => {
    loginAs("admin");
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 6; i++) await flush();

    expect(root.querySelector("[data-testid='ft-create']")).not.toBeNull();
    const input = root.querySelector("[data-testid='ft-new-pattern']") as HTMLInputElement;
    input.value = "工号";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    (root.querySelector("[data-testid='ft-create-btn']") as HTMLElement).click();
    for (let i = 0; i < 6; i++) await flush();
    const posted = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === "POST");
    expect(posted).toBeTruthy();
  });

  it("viewer 无新建区", async () => {
    loginAs("viewer");
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    for (let i = 0; i < 6; i++) await flush();
    expect(root.querySelector("[data-testid='ft-create']")).toBeNull();
  });
});
