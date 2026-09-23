export const SENSITIVE_KEY_RE = /password|passwd|secret|token|authorization|cookie/i;
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
