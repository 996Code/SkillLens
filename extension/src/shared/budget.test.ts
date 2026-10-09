import { describe, it, expect } from "vitest";
import { Budget, stepBudget, withBudget } from "./budget";

// AK2 三级预算传递：剩余制（子<=父、耗尽快败、每次只消费剩余）
// ——治 30s 无界等待（zcode L14-17 余量原则/L749-756 剩余竞速）
describe("Budget", () => {
  it("剩余随时间递减且不为负", async () => {
    const b = new Budget(50);
    await new Promise((r) => setTimeout(r, 60));
    expect(b.leftMs()).toBe(0);
    expect(b.exhausted()).toBe(true);
  });

  it("slice 子预算不晚于父预算", () => {
    const parent = new Budget(10_000);
    const child = parent.slice(0.6);
    expect(child.leftMs()).toBeLessThanOrEqual(parent.leftMs());
    expect(child.leftMs()).toBeGreaterThan(5000);
  });

  it("父耗尽后 slice 出的子预算立即耗尽", async () => {
    const parent = new Budget(30);
    await new Promise((r) => setTimeout(r, 40));
    const child = parent.slice(0.5);
    expect(child.exhausted()).toBe(true);
  });

  it("timeoutError 消息含预算耗尽锚点（四码分类依据）", () => {
    const b = new Budget(1);
    expect(b.timeoutError("fill").message).toContain("预算耗尽");
  });

  it("stepBudget：均分剩余且保底（下限 5s）", () => {
    const run = new Budget(120_000);
    const s1 = stepBudget(run, 10);
    expect(s1.leftMs()).toBeGreaterThanOrEqual(11_000); // 120s/10=12s
    const late = new Budget(6_000);
    const s2 = stepBudget(late, 3);
    expect(s2.leftMs()).toBeLessThanOrEqual(6_000); // 不超父
  });

  it("withBudget：预算耗尽即 reject（不无限等）", async () => {
    const b = new Budget(50);
    const hang = new Promise<string>(() => {}); // 永不 resolve
    await expect(withBudget(hang, b, "probe")).rejects.toThrow("预算耗尽");
  });

  it("withBudget：正常完成不受影响", async () => {
    const b = new Budget(2_000);
    const ok = Promise.resolve("done");
    expect(await withBudget(ok, b, "fast")).toBe("done");
    expect(b.leftMs()).toBeGreaterThan(0);
  });
});
