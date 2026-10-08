import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import AdaptersView from "../src/views/graph/AdaptersView.vue";

// 评审#1（数据破坏 bug）回归：select 失败时 yamlText 必须清空且保存禁用——
// 否则 A 的 YAML 会被 PUT 到 B 上静默毁掉 B 的配置；save 网络错须捕获。

const adapters = [
  { id: "njmind", label: "njmind 内网", base_url: "http://a", has_login: true,
    probe_count: 1, flow_count: 1, chain_count: 1, lints: [] },
  { id: "odoo", label: "Odoo 销售", base_url: "http://b", has_login: false,
    probe_count: 0, flow_count: 0, chain_count: 0, lints: [] },
];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  });
}

/** odoo 的 YAML 读取恒 500；PUT 可通过 opts.putReject 模拟网络错。 */
function mockFetch(opts: { putReject?: boolean } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || "GET").toUpperCase();
    if (method === "PUT") {
      if (opts.putReject) throw new TypeError("network down");
      return jsonResp({ ok: true });
    }
    if (url.endsWith("/api/v1/adapters/njmind/yaml")) return jsonResp({ yaml: "a: 1" });
    if (url.endsWith("/api/v1/adapters/odoo/yaml")) return jsonResp({ detail: "boom" }, 500);
    if (url.endsWith("/api/v1/adapters")) return jsonResp(adapters);
    return new Response("not found", { status: 404 });
  });
}

async function mountView(root: HTMLElement) {
  const app = createApp({ render: () => h(AdaptersView) });
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

function cards(root: HTMLElement): Element[] {
  return Array.from(root.querySelectorAll(".grid .card"));
}

function saveBtn(root: HTMLElement): HTMLButtonElement {
  return root.querySelector(".editor button.primary") as HTMLButtonElement;
}

function textarea(root: HTMLElement): HTMLTextAreaElement {
  return root.querySelector(".editor textarea") as HTMLTextAreaElement;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("AdaptersView 清单编辑（评审#1 数据破坏守卫）", () => {
  it("YAML 加载成功后保存可用", async () => {
    vi.stubGlobal("fetch", mockFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    cards(root)[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    await flush();

    expect(textarea(root).value).toBe("a: 1");
    expect(saveBtn(root).disabled).toBe(false);
  });

  it("加载失败：清空 yamlText、报错、保存禁用——点击保存不发 PUT", async () => {
    const fetchMock = mockFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    // 先选中 A（YAML 上屏），再选中 B（500）——旧内容不得残留
    cards(root)[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    await flush();
    expect(textarea(root).value).toBe("a: 1");

    cards(root)[1].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    await flush();

    expect(root.querySelector(".editor h3")?.textContent).toContain("odoo");
    expect(textarea(root).value).toBe(""); // A 的 YAML 已清空
    expect(root.textContent).toContain("清单加载失败");
    expect(saveBtn(root).disabled).toBe(true);

    saveBtn(root).click();
    await flush();
    const put = fetchMock.mock.calls.find(
      ([, init]) => ((init as RequestInit | undefined)?.method || "").toUpperCase() === "PUT");
    expect(put).toBeUndefined(); // 串档保存被门控挡住
  });

  it("保存网络错：捕获进 feedback，按钮恢复可用", async () => {
    vi.stubGlobal("fetch", mockFetch({ putReject: true }));
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountView(root);
    await flush();
    await flush();

    cards(root)[0].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await flush();
    await flush();

    saveBtn(root).click();
    await flush();
    await flush();

    expect(root.textContent).toContain("保存请求失败");
    expect(root.textContent).toContain("network down");
    expect(saveBtn(root).disabled).toBe(false); // saving 复位
  });
});
