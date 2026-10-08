// @vitest-environment jsdom
// 安全红线：文档 URL 也是证据。injected/net-hook.js 只脱敏 fetch/XHR，
// click/submit/page-load 事件里的 location.href 曾原文入库——?token=… 之类
// 凭据明文进 IndexedDB 与 server raw_event（且 raw_event 会进 LLM 归因 prompt）。
import { describe, expect, it, vi } from "vitest";

const sent: Array<Record<string, unknown>> = [];
vi.stubGlobal("chrome", {
  runtime: {
    sendMessage: (m: { type: string; event?: Record<string, unknown> }) => {
      if (m.type === "skilllens-event" && m.event) sent.push(m.event);
      return Promise.resolve({ recording: true });
    },
    getURL: (p: string) => `chrome-extension://fake/${p}`,
  },
  storage: { onChanged: { addListener: () => {} } },
});
vi.stubGlobal("location", {
  href: "http://a.local/order/9?token=abc123&api_key=k-99&id=5",
});

await import("./capture");
await new Promise((r) => setTimeout(r, 0));   // 等 refreshState 门控就位

function payloads(kind: string, type?: string): Array<Record<string, unknown>> {
  return sent
    .filter((e) => e.kind === kind)
    .map((e) => e.payload as Record<string, unknown>)
    .filter((p) => type === undefined || p.type === type);
}

// sent 不清空：page-load 只在 import 时发一次，click/submit 取最后一条
describe("文档 URL 脱敏", () => {
  it("page-load（navigation）的 url 掩码凭据 query", () => {
    const nav = payloads("navigation", "page-load");
    expect(nav.length).toBeGreaterThan(0);
    const url = String(nav[0].url);
    expect(url).not.toContain("abc123");
    expect(url).not.toContain("k-99");
    expect(url).toContain("id=5");
    expect(url).toContain("token=[REDACTED]");
  });

  it("click 事件的 url 掩码凭据 query", async () => {
    const btn = document.createElement("button");
    btn.textContent = "确定";
    document.body.appendChild(btn);
    btn.dispatchEvent(new Event("click", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 0));
    const clicks = payloads("action", "click");
    expect(clicks.length).toBeGreaterThan(0);
    expect(String(clicks[clicks.length - 1].url)).not.toContain("abc123");
    expect(String(clicks[clicks.length - 1].url)).toContain("[REDACTED]");
  });

  it("submit 事件的 url 掩码凭据 query", async () => {
    const form = document.createElement("form");
    const btn = document.createElement("button");
    btn.type = "submit";
    btn.textContent = "提交";
    form.appendChild(btn);
    document.body.appendChild(form);
    form.dispatchEvent(new Event("submit", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 0));
    const subs = payloads("action", "submit");
    expect(subs.length).toBeGreaterThan(0);
    expect(String(subs[subs.length - 1].url)).not.toContain("abc123");
  });

  it("host 与路径不受影响（目标系统派生依赖首条 navigation 的 host）", () => {
    const nav = payloads("navigation", "page-load");
    expect(String(nav[0].url)).toContain("http://a.local/order/9?");
  });
});
