// J4 PII 规则配置化：基础词表与 server/app/replay/page_snapshot.py、
// injected/net-hook.js 三处同源（CRXJS 原样复制 injected JS，无法 import TS）；
// 漂移由 shared/redact-parity.test.ts 兜住。
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
  // 中文系统（njmind/若依/禅道/JeecG）的表单 label 与字段名形态
  "密码",
  "口令",
  "密钥",
  "令牌",
  "凭证",
  "验证码",
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

/** 体检🟡⑤：fill 步 value_after 回传脱敏——label 命中敏感词表
 * （密码型字段）时置 [REDACTED]，明文不落 received（C3 入库面）。
 * 与 redactValue 同词表（SENSITIVE_KEY_RE 单一源）。 */
export function redactValueAfter(label: string, value: unknown): string {
  const text = String(value ?? "");
  return SENSITIVE_KEY_RE.test(label || "") ? MASK : text;
}

// ---- 执行器网络证据脱敏（与 injected/net-hook.js 同源语义——CDP 路径
// 复用，安全红线：响应体/URL query 中的凭据不得明文出行）----

export function redactNetworkBody(raw: unknown, maxChars = 2000): string {
  const text = String(raw ?? "");
  try {
    return JSON.stringify(redactValue("body", JSON.parse(text))).slice(0, maxChars);
  } catch {
    // 体检🟡④：multipart/form-data——分节结构脱敏复杂且常含文件/密码
    // 字段，宁缺毋漏整段掩码（回放断言不依赖 multipart 明文）
    if (/^--[^\r\n]+\r?\nContent-Disposition/i.test(text.slice(0, 200))) {
      return `[REDACTED multipart body ${text.length}b]`.slice(0, maxChars);
    }
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
