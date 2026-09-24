import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import SkillsList from "../src/views/SkillsList.vue";
import SkillDetail from "../src/views/SkillDetail.vue";

// Task 3 测试：mock fetch 后两视图渲染关键数据（name/status/断言行数）。
// 挂载方式参考 tests/App.spec.ts：createApp + memory router，不引额外测试库。

function mountView(root: HTMLElement, view: unknown, path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/skills", component: { render: () => null } },
      { path: "/skills/:id", component: { render: () => null } },
      { path: "/replay/:skillId", component: { render: () => null } },
    ],
  });
  router.push(path);
  const app = createApp({ render: () => h(view as never) });
  app.use(router);
  app.mount(root);
  return app;
}

function mockFetchBy(routes: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const [prefix, body] of Object.entries(routes)) {
      if (url.includes(prefix)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
    }
    return new Response("not found", { status: 404 });
  });
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("SkillsList", () => {
  it("renders skill cards with name/status/assertion count/run dot", async () => {
    vi.stubGlobal("fetch", mockFetchBy({
      "/api/v1/skills/1/card": {
        id: 1, name: "SaveForm", description: "d", status: "learned",
        confidence: 1.0, evidence_count: 2, alignment_id: 1,
        skeleton: [{ signature: "a|b" }], input_variables: [], param_variables: [],
        assertions: [{ id: 1 }, { id: 2 }, { id: 3 }],
        last_run: { id: 9, status: "pass", mode: "execute", ts: "2026-09-24T10:00:00" },
        window_params: null, notes: "",
      },
      "/api/v1/skills/2/card": {
        id: 2, name: "Cand2", description: "", status: "candidate",
        confidence: 0.6, evidence_count: 1, alignment_id: 2,
        skeleton: [], input_variables: [], param_variables: [],
        assertions: [], last_run: null, window_params: null, notes: "",
      },
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/skills") {
        return new Response(JSON.stringify([
          { id: 2, alignment_id: 2, name: "Cand2", description: "", status: "candidate",
            confidence: 0.6, evidence_count: 1, notes: "" },
          { id: 1, alignment_id: 1, name: "SaveForm", description: "d", status: "learned",
            confidence: 1.0, evidence_count: 2, notes: "" },
        ]), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url === "/api/v1/skills/1/card") {
        return new Response(JSON.stringify({
          id: 1, name: "SaveForm", description: "d", status: "learned",
          confidence: 1.0, evidence_count: 2, alignment_id: 1,
          skeleton: [], input_variables: [], param_variables: [],
          assertions: [{ id: 1 }, { id: 2 }, { id: 3 }],
          last_run: { id: 9, status: "pass", mode: "execute", ts: "2026-09-24T10:00:00" },
          window_params: null, notes: "",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (url === "/api/v1/skills/2/card") {
        return new Response(JSON.stringify({
          id: 2, name: "Cand2", description: "", status: "candidate",
          confidence: 0.6, evidence_count: 1, alignment_id: 2,
          skeleton: [], input_variables: [], param_variables: [],
          assertions: [], last_run: null, window_params: null, notes: "",
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      return new Response("not found", { status: 404 });
    }));

    const root = document.createElement("div");
    document.body.appendChild(root);
    mountView(root, SkillsList, "/skills");
    await flush();
    await flush();

    expect(root.textContent).toContain("SaveForm");
    expect(root.textContent).toContain("Cand2");
    expect(root.textContent).toContain("learned");
    expect(root.textContent).toContain("candidate");
    expect(root.textContent).toContain("100%");
    expect(root.textContent).toContain("未回放"); // last_run=null 的卡
    const card1 = root.querySelectorAll(".card")[1]; // 列表 id 倒序：SaveForm 第二张
    expect(card1.textContent).toContain("3"); // 断言数上屏
    expect(card1.querySelector(".dot-pass")).not.toBeNull(); // run 状态点
    expect(card1.querySelectorAll("a, a *").length).toBeGreaterThan(0);
  });

  it("renders empty state when no skills", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify([]), { status: 200 })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    mountView(root, SkillsList, "/skills");
    await flush();
    expect(root.textContent).toContain("暂无 Skill，先录制并归纳");
  });
});

describe("SkillDetail", () => {
  const card = {
    id: 3, name: "SaveForm", description: "保存表单", status: "learned",
    confidence: 1.0, evidence_count: 2, alignment_id: 1,
    skeleton: [
      { signature: "navigation|page-load" },
      { signature: "action|input|请输入" },
      { signature: "api|POST|/a/1/save" },
    ],
    input_variables: [{ name: "请输入", values: { s1: "旧甲", s2: "旧乙" } }],
    param_variables: [],
    assertions: [
      { id: 1, kind: "api_status", layer: 3,
        payload: { api_template: "/a/1/save", expect_status: 200 } },
      { id: 2, kind: "state_signal", layer: 3,
        payload: { api_template: "/a/1/save", field: "code", expect_value: 200 } },
      { id: 3, kind: "ui_text", layer: 2,
        payload: { label: "备注", before: "a", after: "b" } },
      { id: 4, kind: "field_change", layer: 2,
        payload: { api_template: "/a/1/save", field: "note", before: "n1", after: "n2" } },
    ],
    last_run: { id: 9, status: "shadow", mode: "shadow", ts: "2026-09-24T10:00:00" },
    window_params: { idle_ms: 2000, max_window_ms: 8000, consistent: true },
    notes: "note here",
  };

  it("renders summary/skeleton/variables/assertions table", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify(card), { status: 200 })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    mountView(root, SkillDetail, "/skills/3");
    await flush();

    expect(root.textContent).toContain("SaveForm");
    expect(root.textContent).toContain("learned");
    expect(root.textContent).toContain("保存表单");
    // 骨架逐行
    expect(root.textContent).toContain("api|POST|/a/1/save");
    // 变量值
    expect(root.textContent).toContain("旧甲");
    // 断言行数 = tbody 行数
    const rows = root.querySelectorAll(".block table tbody tr");
    expect(rows.length).toBeGreaterThanOrEqual(6); // 变量1 + 断言4 + 窗口3
    const assertBlock = Array.from(root.querySelectorAll(".block")).find((b) =>
      b.querySelector("h2")?.textContent?.includes("断言"));
    expect(assertBlock?.querySelectorAll("tbody tr").length).toBe(4);
    // 四种 payload 摘要
    expect(root.textContent).toContain("/a/1/save → 200");
    expect(root.textContent).toContain("code=200");
    expect(root.textContent).toContain("备注: a → b");
    expect(root.textContent).toContain("note: n1 → n2");
    // 最近 run
    expect(root.querySelector(".dot-shadow")).not.toBeNull();
    expect(root.textContent).toContain("2026-09-24 10:00:00");
    // 页脚回放入口（Task 5）：链接指向 /replay/3
    const cta = root.querySelector<HTMLAnchorElement>(".replay-btn");
    expect(cta?.getAttribute("href")).toBe("/replay/3");
    expect(cta?.textContent).toContain("回放此 Skill");
  });

  it("renders 404 state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 404 })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    mountView(root, SkillDetail, "/skills/999");
    await flush();
    expect(root.textContent).toContain("404");
  });
});
