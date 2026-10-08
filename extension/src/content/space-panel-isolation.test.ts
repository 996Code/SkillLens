// @vitest-environment jsdom
// AH4b 录制隔离：悬浮面板（data-skilllens-ui）上的点击/提交不得被采集
// ——面板是注入 UI 不是业务操作，录进骨架即污染。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sent: Array<{ type: string; event: Record<string, unknown> }> = [];
vi.stubGlobal("chrome", {
  runtime: {
    sendMessage: (m: { type: string; event?: Record<string, unknown> }) => {
      if (m.type === "skilllens-event" && m.event) sent.push(m as { type: string; event: Record<string, unknown> });
      return Promise.resolve({ recording: true });
    },
    getURL: (p: string) => `chrome-extension://fake/${p}`,
  },
  storage: { onChanged: { addListener: () => {} } },
});

await import("./capture");
await new Promise((r) => setTimeout(r, 0));

function clicks(): Array<Record<string, unknown>> {
  return sent.filter((m) => m.event.kind === "action"
    && (m.event.payload as { type?: string }).type === "click")
    .map((m) => m.event.payload as Record<string, unknown>);
}

beforeEach(() => { sent.length = 0; });
afterEach(() => { document.body.innerHTML = ""; });

describe("悬浮面板 UI 隔离（AH4b）", () => {
  it("data-skilllens-ui 宿主内的点击不采集（shadow DOM composedPath 场景）", () => {
    const host = document.createElement("div");
    host.setAttribute("data-skilllens-ui", "space-panel");
    const inner = document.createElement("button");
    inner.textContent = "执行";
    host.appendChild(inner);
    document.body.appendChild(host);
    inner.dispatchEvent(new MouseEvent("click", { bubbles: true, composed: true }));
    expect(clicks()).toHaveLength(0);
  });

  it("普通业务按钮照常采集（不误伤）", () => {
    const btn = document.createElement("button");
    btn.textContent = "保存";
    document.body.appendChild(btn);
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(clicks()).toHaveLength(1);
  });

  it("面板内表单 submit 不采集", () => {
    const host = document.createElement("form");
    host.setAttribute("data-skilllens-ui", "space-panel");
    document.body.appendChild(host);
    host.dispatchEvent(new Event("submit", { bubbles: true, composed: true }));
    const subs = sent.filter((m) => m.event.kind === "action"
      && (m.event.payload as { type?: string }).type === "submit");
    expect(subs).toHaveLength(0);
  });
});
