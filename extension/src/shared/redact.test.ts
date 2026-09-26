import { buildSensitiveRe, redactValue, SENSITIVE_KEY_RE } from "./redact";

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

describe("buildSensitiveRe（J4 PII 规则配置化工厂）", () => {
  it("追加自定义模式命中（子串+大小写不敏感）", () => {
    const re = buildSensitiveRe(["idcard", "phone"]);
    expect(re.test("idcard")).toBe(true);
    expect(re.test("user_idcard_number")).toBe(true);
    expect(re.test("IDCard")).toBe(true);
  });
  it("默认正则不变：不含自定义字段", () => {
    expect(SENSITIVE_KEY_RE.test("idcard")).toBe(false);
    expect(SENSITIVE_KEY_RE.test("phone")).toBe(false);
    expect(SENSITIVE_KEY_RE.test("password")).toBe(true);
  });
  it("空追加等价于默认词表", () => {
    const re = buildSensitiveRe([]);
    expect(re.test("password")).toBe(true);
    expect(re.test("idcard")).toBe(false);
  });
});
