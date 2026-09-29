// @vitest-environment jsdom
// S42：input 事件去抖采集——change 依赖 blur+dirty 标记，程序化填值
// （fill 不置 dirty）与框架回显覆盖时序下不可靠。input 是可靠信号。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// chrome API 桩（capture.ts 顶层即用）
const sent: Array<{ type: string; event: Record<string, unknown> }> = [];
vi.stubGlobal("chrome", {
  runtime: {
    sendMessage: (m: { type: string; event?: Record<string, unknown> }) => {
      if (m.type === "skilllens-event" && m.event) sent.push(m as { type: string; event: Record<string, unknown> });
      return Promise.resolve({ recording: true });
    },
    getURL: (p: string) => `chrome-extension://fake/${p}`,
  },
  storage: {
    onChanged: { addListener: () => {} },
  },
});

await import("./capture");
// refreshState 是异步的——等一轮微任务让 recording 门控就位
await new Promise((r) => setTimeout(r, 0));

function makeInput(ph = "请输入岗位名称", value = ""): HTMLInputElement {
  const el = document.createElement("input");
  el.placeholder = ph;
  el.value = value;
  document.body.appendChild(el);
  return el;
}

function fire(el: Element, type: string): void {
  el.dispatchEvent(new Event(type, { bubbles: true }));
}

function inputActions(): Array<Record<string, unknown>> {
  return sent.filter((m) => m.type === "skilllens-event")
    .map((m) => m.event)
    .filter((e) => e.kind === "action" && (e.payload as { type?: string }).type === "input");
}

beforeEach(() => {
  vi.useFakeTimers();
  sent.length = 0;
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = "";
});

describe("capture input 去抖采集（S42）", () => {
  it("input 事件去抖后发一次终值", async () => {
    const el = makeInput();
    el.value = "甲";
    fire(el, "input");
    el.value = "甲乙";
    fire(el, "input");
    vi.advanceTimersByTime(700);
    await vi.advanceTimersByTimeAsync(0);
    const acts = inputActions();
    expect(acts).toHaveLength(1);
    expect((acts[0].payload as { value?: string }).value).toBe("甲乙");
  });

  it("change 与近期 input 同值去重（真实键入 blur 不双发）", async () => {
    const el = makeInput();
    el.value = "甲";
    fire(el, "input");
    vi.advanceTimersByTime(700);
    fire(el, "change"); // blur 触发，值同
    const acts = inputActions();
    expect(acts).toHaveLength(1);
  });

  it("无近期 input 时 change 照常采集（纯 select/程序化 change）", async () => {
    const el = makeInput();
    el.value = "乙";
    fire(el, "change");
    const acts = inputActions();
    expect(acts).toHaveLength(1);
    expect((acts[0].payload as { value?: string }).value).toBe("乙");
  });

  it("点击锚点前 flush 挂起的 input（顺序保证：input 先于 click）", async () => {
    const el = makeInput();
    el.value = "丙";
    fire(el, "input");
    // 300ms 后用户点按钮（未到 600ms 去抖）
    vi.advanceTimersByTime(300);
    const btn = document.createElement("button");
    btn.textContent = "确定";
    document.body.appendChild(btn);
    fire(btn, "click");
    await vi.advanceTimersByTimeAsync(0);
    const kinds = sent.filter((m) => m.type === "skilllens-event")
      .map((m) => `${(m.event as { kind?: string }).kind}:${((m.event as { payload?: { type?: string } }).payload || {}).type || ""}`);
    // input action 必须在 click action 之前
    const inputIdx = kinds.findIndex((k) => k === "action:input");
    const clickIdx = kinds.findIndex((k) => k === "action:click");
    expect(inputIdx).toBeGreaterThanOrEqual(0);
    expect(clickIdx).toBeGreaterThan(inputIdx);
  });
});
