import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import TimelineView from "../src/views/TimelineView.vue";

// S32 链路时间线测试：①时间轴渲染（类型徽标+标题+摘要）
// ②类型过滤 chip ③LLM 项点击展开完整 prompt/response（按需拉取）
// ④skill 项展开下钻链接。
// 挂载方式同 AuditView.spec.ts：createApp + memory router；fetch mock 按 URL 路由。

const items = [
  { type: "llm", id: 3, title: "LLM skill_naming", subtitle: "fake · 500ms · 100/20 tokens",
    ts: "2026-09-28T12:33:00" },
  { type: "skill", id: 5, title: "Skill #5 SaveForm", subtitle: "learned · 置信度 90% · 证据 2",
    ts: "2026-09-28T12:32:00" },
  { type: "session", id: "sess-aaaa1111", title: "采集 sess-aaaa",
    subtitle: "事件 5 · 语义 1 · 时间线会话", ts: "2026-09-28T12:30:00" },
  { type: "replay", id: 9, title: "回放 #9", subtitle: "pass · execute · 2 步 · 1 断言 · 800ms",
    ts: "2026-09-28T12:28:00" },
];

const llmDetail = {
  id: 3, purpose: "skill_naming", provider: "fake", model: "fake-model",
  prompt: "FULL-PROMPT-请为以下骨架命名", response: "FULL-RESPONSE-{\"name\":\"SaveForm\"}",
  prompt_tokens: 100, completion_tokens: 20, latency_ms: 500,
  created_at: "2026-09-28T12:33:00",
};

const replayRunDetail = {
  id: 9, skill_id: 5, mode: "execute", status: "pass",
  plan: {
    url: "http://t/f", steps: [],
    step_screenshots: {
      dir: "/tmp/shots", files: ["start.png", "step-01.png", "step-02.png"],
    },
  },
  executed: [
    { kind: "input", name: "请输入", value: "v", ok: true, screenshot: "step-01.png" },
    { kind: "click", label: "保存", ok: true, screenshot: "step-02.png" },
  ],
  assertion_results: [], attribution: null, artifact_path: "",
};

function mockTimelineFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/audit/llm-logs/3")) {
      return new Response(JSON.stringify(llmDetail), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/replay-runs/9/step-screenshot")) {
      return new Response(new Blob(["png"], { type: "image/png" }), { status: 200 });
    }
    if (url.includes("/api/v1/replay-runs/9")) {
      return new Response(JSON.stringify(replayRunDetail), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/timeline")) {
      return new Response(JSON.stringify(items), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountTimeline(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/", component: { render: () => null } },
      { path: "/timeline", component: { render: () => null } },
      { path: "/skills/:id", component: { render: () => null } },
      { path: "/audit", component: { render: () => null } },
    ],
  });
  await router.push("/timeline");
  const app = createApp({ render: () => h(TimelineView) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("TimelineView", () => {
  it("renders timeline items with type badges, titles and subtitles", async () => {
    vi.stubGlobal("fetch", mockTimelineFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountTimeline(root);
    await flush();
    await flush();

    const list = root.querySelector("[data-testid='timeline-list']");
    expect(list).not.toBeNull();
    expect(root.querySelectorAll(".tl-item").length).toBe(4);
    // 类型中文徽标 + 标题 + 摘要
    expect(root.textContent).toContain("LLM skill_naming");
    expect(root.textContent).toContain("Skill #5 SaveForm");
    expect(root.textContent).toContain("置信度 90%");
    expect(root.textContent).toContain("事件 5 · 语义 1");
    expect(root.textContent).toContain("回放 #9");
    // 时间格式化（T → 空格）
    expect(root.textContent).toContain("2026-09-28 12:33");
    // 过滤 chip 带计数
    expect(root.textContent).toContain("全部 4");
    expect(root.textContent).toContain("LLM 1");
  });

  it("filters items by type chip", async () => {
    vi.stubGlobal("fetch", mockTimelineFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountTimeline(root);
    await flush();
    await flush();

    (root.querySelector("[data-testid='filter-llm']") as HTMLElement).click();
    await flush();
    expect(root.querySelectorAll(".tl-item").length).toBe(1);
    expect(root.textContent).toContain("LLM skill_naming");
    expect(root.textContent).not.toContain("Skill #5 SaveForm");

    // 再点一次取消过滤
    (root.querySelector("[data-testid='filter-llm']") as HTMLElement).click();
    await flush();
    expect(root.querySelectorAll(".tl-item").length).toBe(4);
  });

  it("expands llm item to fetch and show full prompt/response", async () => {
    const fetchMock = mockTimelineFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountTimeline(root);
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='llm-detail']")).toBeNull();
    (root.querySelector("[data-testid='tl-llm']") as HTMLElement).click();
    await flush();
    await flush();

    const detail = root.querySelector("[data-testid='llm-detail']");
    expect(detail).not.toBeNull();
    // 完整 IO（非 200 字符摘要）
    expect(detail?.textContent).toContain("FULL-PROMPT-请为以下骨架命名");
    expect(detail?.textContent).toContain("FULL-RESPONSE-{\"name\":\"SaveForm\"}");
    expect(detail?.textContent).toContain("prompt（100 tokens）");
    expect(detail?.textContent).toContain("response（20 tokens · 500ms）");
    // 详情端点按需拉取（一次）
    const detailCalls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/api/v1/audit/llm-logs/3"));
    expect(detailCalls.length).toBe(1);

    // 再点收起
    (root.querySelector("[data-testid='tl-llm']") as HTMLElement).click();
    await flush();
    expect(root.querySelector("[data-testid='llm-detail']")).toBeNull();
  });

  it("expands skill item to show drill-down link", async () => {
    vi.stubGlobal("fetch", mockTimelineFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountTimeline(root);
    await flush();
    await flush();

    (root.querySelector("[data-testid='tl-skill']") as HTMLElement).click();
    await flush();
    const link = root.querySelector<HTMLAnchorElement>("a[href='/skills/5']");
    expect(link).not.toBeNull();
    expect(link?.textContent).toContain("下钻查看");
  });

  it("expands replay item to show step screenshot wall", async () => {
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => "blob:mock",
    }));
    const fetchMock = mockTimelineFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountTimeline(root);
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='replay-detail']")).toBeNull();
    (root.querySelector("[data-testid='tl-replay']") as HTMLElement).click();
    await flush();
    await flush();
    await flush();

    const detail = root.querySelector("[data-testid='replay-detail']");
    expect(detail).not.toBeNull();
    expect(detail?.textContent).toContain("3 张步骤画面");
    // 截图墙：3 张图 + 步骤说明（起始页 + input/click 步骤）
    const imgs = root.querySelectorAll("[data-testid='shot-grid'] img");
    expect(imgs.length).toBe(3);
    expect((imgs[0] as HTMLImageElement).src).toBe("blob:mock");
    const captions = Array.from(
      root.querySelectorAll("[data-testid='shot-grid'] figcaption"))
      .map((c) => c.textContent);
    expect(captions).toContain("起始页");
    expect(captions).toContain("input 请输入");
    expect(captions).toContain("click 保存");
    // 每张图各拉一次
    const shotCalls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("/step-screenshot?file="));
    expect(shotCalls.length).toBe(3);
  });
});
