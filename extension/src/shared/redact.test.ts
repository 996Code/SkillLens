import { redactValue } from "./redact";

describe("redactValue", () => {
  it("敏感 key 被掩码", () => {
    expect(redactValue("password", "abc123")).toBe("[REDACTED]");
    expect(redactValue("Authorization", "Bearer xx")).toBe("[REDACTED]");
    expect(redactValue("access_token", "t")).toBe("[REDACTED]");
  });
  it("普通 key 原样返回", () => {
    expect(redactValue("order_id", 92382)).toBe(92382);
    expect(redactValue("customer", "张三")).toBe("张三");
  });
  it("嵌套 dict 递归脱敏", () => {
    expect(redactValue("body", { user: "a", password: "b" })).toEqual({ user: "a", password: "[REDACTED]" });
  });
});
