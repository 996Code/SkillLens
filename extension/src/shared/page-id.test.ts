import { describe, expect, it, vi } from "vitest";
import { makePageId } from "./page-id";

describe("makePageId", () => {
  it("同实例内稳定", () => {
    expect(makePageId()).toBe(makePageId());
  });
  it("长度 ≤ 40 且非空", () => {
    const id = makePageId();
    expect(id.length).toBeGreaterThan(0);
    expect(id.length).toBeLessThanOrEqual(40);
  });
  it("模块重置后生成新 id（模拟新页面实例）", async () => {
    const first = makePageId();
    vi.resetModules();
    const { makePageId: fresh } = await import("./page-id");
    expect(fresh()).not.toBe(first);
  });
});
