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
