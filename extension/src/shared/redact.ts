// J4 PII 规则配置化：基础词表与 server/app/replay/page_snapshot.py 同源；
// buildSensitiveRe(extraPatterns) 供后续配置注入通道（popup 设置页）追加自定义敏感字段
export const BASE_SENSITIVE_PATTERNS = [
  "password",
  "passwd",
  "secret",
  "token",
  "authorization",
  "cookie",
  "api_key",
  "apikey",
  "private_key",
  "credential",
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
  if (Array.isArray(value)) return value.map((v) => redactValue(key, v));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, redactValue(k, v)]),
    );
  }
  return value;
}

// ---- 执行器网络证据脱敏（与 injected/net-hook.js 同源语义——CDP 路径
// 复用，安全红线：响应体/URL query 中的凭据不得明文出行）----

export function redactNetworkBody(raw: unknown, maxChars = 2000): string {
  const text = String(raw ?? "");
  try {
    return JSON.stringify(redactValue("body", JSON.parse(text))).slice(0, maxChars);
  } catch {
    // 非 JSON 字符串：urlencoded 键值形态脱敏（password=x&…），其余原样截断
    return text
      .replace(/(^|[&;])([^=&;]+)=([^&;]*)/g,
        (m, p, k) => (SENSITIVE_KEY_RE.test(k) ? `${p}${k}=${MASK}` : m))
      .slice(0, maxChars);
  }
}

export function redactNetworkUrl(u: string): string {
  // 字符串级替换而非 URL API——searchParams.set 会把 [REDACTED]
  // 编码成 %5BREDACTED%5D，语义同 net-hook redactFormString
  const i = u.indexOf("?");
  if (i < 0) return u;
  const q = u.slice(i + 1).replace(
    /(^|[&;])([^=&;#]+)=([^&#]*)/g,
    (m, p, k) => (SENSITIVE_KEY_RE.test(k) ? `${p}${k}=${MASK}` : m),
  );
  return u.slice(0, i + 1) + q;
}
