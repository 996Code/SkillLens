import { putEvent, takeEvents } from "../store/idb";
import { AGENT_URL } from "../shared/types";
import type { RawEvent } from "../shared/types";

const BATCH = 50;
const MAX_RETRIES = 3;

// 内存重试计数（POC：service worker 重启即清零；Sprint 1 改为持久重试队列）
const retries = new Map<string, number>();

function eventKey(e: RawEvent): string {
  return `${e.ts}:${e.seq}:${e.kind}`;
}

async function flush(): Promise<void> {
  const rows = await takeEvents(BATCH);
  if (rows.length === 0) return;
  // 同一 session 的事件分组上报（POC：一个 content script 一个 session）
  const bySession = new Map<string, RawEvent[]>();
  for (const { event } of rows) {
    const sid = event.payload.__session_id as string;
    const list = bySession.get(sid) ?? [];
    list.push(event);
    bySession.set(sid, list);
  }
  for (const [sid, events] of bySession) {
    try {
      const resp = await fetch(`${AGENT_URL}/sessions/${sid}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(events),
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      for (const e of events) retries.delete(eventKey(e));
    } catch (err) {
      console.warn("skilllens upload failed, requeue", err);
      for (const e of events) {
        const key = eventKey(e);
        const n = (retries.get(key) ?? 0) + 1;
        if (n > MAX_RETRIES) {
          // POC 阶段可接受：超过重试上限丢弃
          console.warn("skilllens drop event after retries", key);
          continue;
        }
        retries.set(key, n);
        await putEvent(e); // 失败回退
      }
    }
  }
}

async function loop(): Promise<void> {
  await flush();
  chrome.alarms.create("flush", { periodInMinutes: 0.1 });
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === "events-pending") void flush();
});
chrome.alarms.onAlarm.addListener(() => void flush());
void loop();
