// @vitest-environment jsdom
// S42 安全红线：net-hook 的 reqBody 字符串形态与 URL query 凭据必须脱敏。
// net-hook 是 MAIN world 纯 JS 脚本（CRXJS 原样复制），此处动态 import 验证其包装行为。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function fakeResponse(body = "{}") {
  return {
    status: 200,
    clone: () => ({ text: async () => body }),
  } as unknown as Response;
}

describe("net-hook 脱敏", () => {
  let postSpy: ReturnType<typeof vi.fn>;
  let origFetch: typeof fetch;

  beforeEach(async () => {
    postSpy = vi.fn();
    window.postMessage = postSpy as unknown as typeof window.postMessage;
    origFetch = vi.fn(async () => fakeResponse()) as unknown as typeof fetch;
    window.fetch = origFetch;
    vi.resetModules();
    await import("./net-hook.js");
  });

  afterEach(() => {
    window.fetch = origFetch;
  });

  async function lastDetail() {
    for (let i = 0; i < 50 && postSpy.mock.calls.length === 0; i++) {
      await new Promise((r) => setTimeout(r, 10));
    }
    expect(postSpy.mock.calls.length).toBeGreaterThan(0);
    return postSpy.mock.calls[0][0].detail as Record<string, unknown>;
  }

  it("reqBody 为 JSON 字符串时密码字段脱敏", async () => {
    await window.fetch("/api/login", {
      method: "POST",
      body: JSON.stringify({ username: "admin", password: "secret123" }),
    });
    const detail = await lastDetail();
    expect(String(detail.reqBody)).not.toContain("secret123");
    expect(String(detail.reqBody)).toContain("[REDACTED]");
    expect(String(detail.reqBody)).toContain("admin");
  });

  it("reqBody 为 urlencoded 字符串时敏感键脱敏", async () => {
    await window.fetch("/api/login", {
      method: "POST",
      body: "user=admin&password=secret123&ok=1",
    });
    const detail = await lastDetail();
    expect(String(detail.reqBody)).not.toContain("secret123");
    expect(String(detail.reqBody)).toContain("admin");
  });

  it("URL query 中的敏感参数值脱敏", async () => {
    await window.fetch("/api/data?token=abc123&foo=1");
    const detail = await lastDetail();
    expect(String(detail.url)).not.toContain("abc123");
    expect(String(detail.url)).toContain("foo=1");
  });

  it("非敏感请求保持原文（不误伤）", async () => {
    await window.fetch("/api/data?q=hello", {
      method: "POST",
      body: JSON.stringify({ name: "订单A" }),
    });
    const detail = await lastDetail();
    expect(String(detail.url)).toContain("q=hello");
    expect(String(detail.reqBody)).toContain("订单A");
  });
});

// 宪法 C3「全链路落库（含失败调用）」：原实现 fetch reject 直接抛出无 post、
// XHR 只挂 load——网络错误/超时/中止的调用在录制侧完全消失，回放对账无从判因。
describe("net-hook 失败调用留痕（C3）", () => {
  let postSpy: ReturnType<typeof vi.fn>;
  let origFetch: typeof fetch;
  const realOpen = XMLHttpRequest.prototype.open;
  const realSend = XMLHttpRequest.prototype.send;

  beforeEach(async () => {
    postSpy = vi.fn();
    window.postMessage = postSpy as unknown as typeof window.postMessage;
    // 桩掉底层 send/open：不真发请求，由测试手动派发事件
    XMLHttpRequest.prototype.open = function () { /* noop */ } as typeof realOpen;
    XMLHttpRequest.prototype.send = function () { /* noop */ } as typeof realSend;
    origFetch = vi.fn(async () => fakeResponse()) as unknown as typeof fetch;
    window.fetch = origFetch;
    vi.resetModules();
    await import("./net-hook.js");
  });

  afterEach(() => {
    window.fetch = origFetch;
    XMLHttpRequest.prototype.open = realOpen;
    XMLHttpRequest.prototype.send = realSend;
  });

  it("fetch 网络失败：post status=0 后原样抛出（不吞页面异常）", async () => {
    window.fetch = vi.fn(async () => { throw new TypeError("Failed to fetch"); }) as unknown as typeof fetch;
    vi.resetModules();
    await import("./net-hook.js");
    await expect(window.fetch("/api/save?token=abc", {
      method: "POST", body: "password=pw123&x=1",
    })).rejects.toThrow("Failed to fetch");
    expect(postSpy).toHaveBeenCalled();
    const detail = postSpy.mock.calls[0][0].detail as Record<string, unknown>;
    expect(detail.status).toBe(0);
    expect(detail.error).toBe("network");
    expect(detail.method).toBe("POST");
    // 失败调用同样走脱敏（红线不因失败而豁免）
    expect(String(detail.url)).not.toContain("abc");
    expect(String(detail.reqBody)).not.toContain("pw123");
  });

  it("XHR error 事件留痕 status=0", () => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/x");
    xhr.send("a=1");
    xhr.dispatchEvent(new Event("error"));
    expect(postSpy).toHaveBeenCalled();
    const detail = postSpy.mock.calls[0][0].detail as Record<string, unknown>;
    expect(detail.status).toBe(0);
    expect(detail.error).toBe("network");
    expect(detail.url).toContain("/api/x");
  });

  it("XHR timeout / abort 事件分别留痕", () => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", "/api/y");
    xhr.send();
    xhr.dispatchEvent(new Event("timeout"));
    xhr.dispatchEvent(new Event("abort"));
    const kinds = postSpy.mock.calls.map((c) => (c[0].detail as Record<string, unknown>).error);
    expect(kinds).toEqual(["timeout", "abort"]);
  });

  it("成功调用不受影响（真实状态码，无 error 字段）", () => {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", "/api/z");
    Object.defineProperty(xhr, "status", { value: 200 });
    Object.defineProperty(xhr, "responseText", { value: '{"ok":true}' });
    xhr.send();
    xhr.dispatchEvent(new Event("load"));
    const detail = postSpy.mock.calls[0][0].detail as Record<string, unknown>;
    expect(detail.status).toBe(200);
    expect(detail.error).toBeUndefined();
    expect(String(detail.resBody)).toContain("ok");
  });
});
