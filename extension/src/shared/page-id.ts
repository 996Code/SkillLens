let cached: string | null = null;

export function makePageId(): string {
  if (cached) return cached;
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    cached = crypto.randomUUID();
  } else {
    cached = Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }
  return cached;
}
