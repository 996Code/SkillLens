// J4 PII 规则配置化：基础词表与 server/app/replay/page_snapshot.py 同源；
// buildSensitiveRe(extraPatterns) 供后续配置注入通道（popup 设置页）追加自定义敏感字段
export const BASE_SENSITIVE_PATTERNS = [
  "password",
  "passwd",
  "secret",
  "token",
  "authorization",
  "cookie",
];

export function buildSensitiveRe(extraPatterns: string[] = []): RegExp {
  const parts = [
    ...BASE_SENSITIVE_PATTERNS,
    ...extraPatterns.map((p) => p.trim()).filter(Boolean),
  ];
  return new RegExp(parts.join("|"), "i");
}

export const SENSITIVE_KEY_RE = buildSensitiveRe();
const MASK = "[REDACTED]";

export function redactValue(key: string, value: unknown): unknown {
  if (SENSITIVE_KEY_RE.test(key)) return MASK;
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, redactValue(k, v)]),
    );
  }
  return value;
}
