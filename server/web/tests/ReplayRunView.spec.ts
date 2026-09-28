import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import ReplayRunView from "../src/views/ReplayRunView.vue";

// S34 块 1：回放 run 详情页测试——①头部（状态/mode/flaky/耗时/时间）
// ②执行步骤表 ③截图墙（ShotGallery）+ 点击放大 lightbox ④断言明细+归因。
// 挂载方式同 TimelineView.spec.ts；fetch mock 按 URL 路由。

const runDetail = {
  id: 9, skill_id: 5, mode: "execute", status: "fail", flaky: true,
  duration_ms: 4321, created_at: "2026-09-28T12:00:00",
  plan: {
    url: "http://t/f", steps: [],
    step_screenshots: {
      dir: "/tmp/shots", files: ["start.png", "step-01.png"],
    },
  },
  executed: [
    { kind: "input", name: "请输入", value: "v", ok: true, strategy: "placeholder",
      screenshot: "step-01.png" },
    { kind: "click", label: "保存", ok: false, error: "semantic locate failed" },
  ],
  assertion_results: [
    { kind: "api_status", payload: { api_template: "/a/1/save", expect_status: 200 },
      observed_status: 200, passed: true },
    { kind: "ui_text", payload: { label: "提示", before: "a", after: "b" },
      observed_status: null, passed: false },
  ],
  attribution: "页面视觉回归失败：截图差异比例 7.7%",
  artifact_path: "",
};

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/step-screenshot?file=")) {
      return new Response(new Blob(["png"], { type: "image/png" }), { status: 200 });
    }
    if (url.includes("/api/v1/replay-runs/9")) {
      return new Response(JSON.stringify(runDetail), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountView(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/replay-runs/:runId", component: { render: () => null } },
      { path: "/skills/:id", component: { render: () => null } },
      { path: "/timeline", component: { render: () => null } },
    ],
  });
  await router.push("/replay-runs/9");
  const app = createApp({ render: () => h(ReplayRunView) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("ReplayRunView", () => {
  it("renders run header, steps, assertions and attribution", async () => {
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();
    await flush();

    // 头部：状态大字 + mode/flaky 徽标 + 耗时 + 时间 + skill 链接
    expect(root.querySelector(".run-status")?.textContent).toContain("fail");
    expect(root.textContent).toContain("flaky");
    expect(root.textContent).toContain("4321ms");
    expect(root.textContent).toContain("2026-09-28 12:00");
    const skillLink = root.querySelector<HTMLAnchorElement>("a[href='/skills/5']");
    expect(skillLink?.textContent).toContain("Skill #5");

    // 执行步骤表：2 步（ok/failed + 定位策略 + 失败原因）
    expect(root.textContent).toContain("placeholder");
    expect(root.textContent).toContain("semantic locate failed");

    // 断言明细 + 归因
    expect(root.textContent).toContain("/a/1/save → 200");
    expect(root.textContent).toContain("FAILED");
    expect(root.textContent).toContain("视觉回归失败");
  });

  it("shows screenshot wall and opens lightbox on click", async () => {
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();
    await flush();

    const imgs = root.querySelectorAll("[data-testid='shot-grid'] img");
    expect(imgs.length).toBe(2);
    expect(root.textContent).toContain("起始页");
    expect(root.textContent).toContain("input 请输入");

    // 点击缩略图 → lightbox（Teleport 到 body）
    expect(document.querySelector("[data-testid='shot-lightbox']")).toBeNull();
    (root.querySelector(".shot-card") as HTMLElement).click();
    await flush();
    const lightbox = document.querySelector("[data-testid='shot-lightbox']");
    expect(lightbox).not.toBeNull();
    const big = lightbox?.querySelector("img");
    expect((big as HTMLImageElement)?.src).toBe("blob:mock");

    // 点遮罩关闭
    (lightbox as HTMLElement).click();
    await flush();
    expect(document.querySelector("[data-testid='shot-lightbox']")).toBeNull();
  });
});
