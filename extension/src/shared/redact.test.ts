import { buildSensitiveRe, redactNetworkBody, redactNetworkUrl, redactValue, SENSITIVE_KEY_RE } from "./redact";

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

describe("词表扩充（安全红线评审：常见凭据形态）", () => {
  it("api_key / apikey / private_key / credential 命中", () => {
    expect(SENSITIVE_KEY_RE.test("api_key")).toBe(true);
    expect(SENSITIVE_KEY_RE.test("apikey")).toBe(true);
    expect(SENSITIVE_KEY_RE.test("private_key")).toBe(true);
    expect(SENSITIVE_KEY_RE.test("client_credential")).toBe(true);
  });
});

describe("redactNetworkBody（执行器 CDP 网络证据脱敏）", () => {
  it("JSON 响应体递归脱敏敏感键", () => {
    const body = JSON.stringify({ token: "abc", user: { api_key: "k1", name: "n" } });
    const out = JSON.parse(redactNetworkBody(body));
    expect(out.token).toBe("[REDACTED]");
    expect(out.user.api_key).toBe("[REDACTED]");
    expect(out.user.name).toBe("n");
  });
  it("urlencoded 字符串脱敏", () => {
    const body = "username=a&password=secret123&ok=1";
    expect(redactNetworkBody(body)).toBe("username=a&password=[REDACTED]&ok=1");
  });
  it("普通文本原样截断", () => {
    expect(redactNetworkBody("<html>ok</html>")).toBe("<html>ok</html>");
    expect(redactNetworkBody("x".repeat(5000), 100).length).toBe(100);
  });
});

describe("redactNetworkUrl", () => {
  it("URL query 凭据参数掩码", () => {
    expect(redactNetworkUrl("http://a.local/x?token=abc&ok=1"))
      .toBe("http://a.local/x?token=[REDACTED]&ok=1");
  });
  it("无敏感参数原样返回", () => {
    expect(redactNetworkUrl("http://a.local/x?id=5")).toBe("http://a.local/x?id=5");
  });
  it("非法 URL 原样返回不抛", () => {
    expect(redactNetworkUrl("not a url ://")).toBe("not a url ://");
  });
});
