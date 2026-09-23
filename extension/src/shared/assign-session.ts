import type { RawEvent } from "./types";

export function assignSession(
  events: RawEvent[],
  sessionId: string | null,
): { assigned: RawEvent[]; deferred: RawEvent[] } {
  const assigned: RawEvent[] = [];
  const deferred: RawEvent[] = [];
  for (const e of events) {
    const sid = (e.payload.__session_id as string) ?? "";
    if (sid) {
      assigned.push(e);
    } else if (sessionId) {
      assigned.push({ ...e, payload: { ...e.payload, __session_id: sessionId } });
    } else {
      deferred.push(e);
    }
  }
  return { assigned, deferred };
}
