import { describe, expect, it } from "vitest";
import { classifyErr, describeFailure, isAttachConflict } from "./failures";

// AK6 批次1：插件侧四码分类（与 server failures.py 同词表——
// 双端一致性锚点：本测试的形态清单须与 test_exec_failures.py 对齐维护）
describe("classifyErr", () => {
  it("取消最优先——AbortError 含 timeout 字样也判 cancelled", () => {
    expect(classifyErr(new Error("AbortError: The operation was aborted"))).toBe("cancelled");
  });

  it("api timeout 30s（executor.ts api() 的超时形态）判 timeout", () => {
    expect(classifyErr(new Error("api timeout 30s"))).toBe("timeout");
  });

  it("预算耗尽判 timeout（budget.timeoutError 锚点）", () => {
    expect(classifyErr(new Error("run 预算耗尽 budget exhausted"))).toBe("timeout");
  });

  it("attach 冲突判 fatal——不重试（620 run 风暴实证形态）", () => {
    const e = new Error(
      "Another debugger is already attached to the tab with id: 1043799610");
    expect(classifyErr(e)).toBe("fatal");
    expect(isAttachConflict(e)).toBe(true);
    expect(describeFailure(e).retryable).toBe(false);
    expect(describeFailure(e).plain).toContain("DevTools");
  });

  it("瞬态白名单判 transient——retryable（重建上下文后重试有效）", () => {
    for (const msg of [
      "Execution context was destroyed",
      "Frame was detached",
      "Target closed",
      "Session with given ID not found",
    ]) {
      expect(classifyErr(new Error(msg))).toBe("transient");
    }
    expect(describeFailure(new Error("Target closed")).retryable).toBe(true);
  });

  it("其余（选择器/业务错）判 fatal", () => {
    expect(classifyErr(new Error("semantic locate failed: 保存"))).toBe("fatal");
  });
});
