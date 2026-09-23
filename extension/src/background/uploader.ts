import { putEvent, takeEvents } from "../store/idb";
import { AGENT_URL, EVENT_MSG } from "../shared/types";
import type { RawEvent } from "../shared/types";
import { assignSession } from "../shared/assign-session";
import { getRecordingState, startRecording, stopRecording } from "./session";

// chrome.storage.session 默认 accessLevel 为 TRUSTED_CONTEXTS（仅扩展页面可读），
// content script 属于非受信上下文读不到——SW 启动时放开一次，
// 否则录制门控（capture 读 sl_recording）完全失效。
void chrome.storage.session.setAccessLevel({ accessLevel: "TRUSTED_AND_UNTRUSTED_CONTEXTS" });

const BATCH = 50;
const MAX_RETRIES = 3;

// 内存重试计数（POC：service worker 重启即清零；Sprint 1 改为持久重试队列）
const retries = new Map<string, number>();

function eventKey(e: RawEvent): string {
  return `${e.ts}:${e.seq}:${e.kind}`;
}

let flushing = false;

async function flush(): Promise<void> {
  // 防并发：消息驱动下多个 skilllens-event 可能同时触发 flush，
  // takeEvents 的 getAll+delete 非原子，并发会导致同一事件重复上报。
  // 被跳过的事件由后续消息或 alarms 定时兜底。
  if (flushing) return;
  flushing = true;
  try {
    // 上报前回填活跃 session：T7 后 CS 发来的事件 __session_id 恒为 ""，
    // 有活跃 session 则回填后上报；无 session（断连期未录制）则写回缓冲，
    // 不丢弃、不计入重试（等待下次 flush 时机）。
    const state = await getRecordingState();
    await doFlush(state.sessionId);
  } finally {
    flushing = false;
  }
}

// 同一 session 的事件分组上报（POC：一个 content script 一个 session）。
// 返回成功上报的事件数；失败事件按重试计数回退，超限丢弃。
async function uploadGrouped(assigned: RawEvent[]): Promise<number> {
  const bySession = new Map<string, RawEvent[]>();
  for (const event of assigned) {
    const sid = event.payload.__session_id as string;
    const list = bySession.get(sid) ?? [];
    list.push(event);
    bySession.set(sid, list);
  }
  let ok = 0;
  for (const [sid, events] of bySession) {
    try {
      const resp = await fetch(`${AGENT_URL}/sessions/${sid}/events`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(events),
      });
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      for (const e of events) retries.delete(eventKey(e));
      ok += events.length;
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
  return ok;
}

async function doFlush(sid: string | null): Promise<void> {
  const rows = await takeEvents(BATCH);
  if (rows.length === 0) return;
  const { assigned, deferred } = assignSession(rows.map((r) => r.event), sid);
  for (const e of deferred) await putEvent(e);
  if (assigned.length === 0) return;
  const n = await uploadGrouped(assigned);
  console.debug("[skilllens] flush ok", n);
}

// 停止录制时的最终上报：由 stopRecording 在清除 storage 标记之前调用，
// 用停止前的 sid 兜底上报缓冲事件——否则清除后到达的 flush 读到
// sessionId 为 null，缓冲事件全进 deferred 永久滞留（session 0 事件的根因）。
// 单独执行、不抢 flushing 锁（停止时不会有并发写入，可接受）；
// 无 sid 可回填的 deferred 事件直接丢弃并告警（录制已结束，没有后续回填时机）。
export async function finalFlushWithSession(sid: string | null): Promise<void> {
  const rows = await takeEvents(500);
  const { assigned, deferred } = assignSession(rows.map((r) => r.event), sid);
  if (deferred.length > 0) {
    console.warn(`[skilllens] final flush: drop ${deferred.length} events without session`);
  }
  if (assigned.length === 0) return;
  const n = await uploadGrouped(assigned);
  console.debug("[skilllens] final flush done", n);
}

async function loop(): Promise<void> {
  await flush();
  chrome.alarms.create("flush", { periodInMinutes: 0.1 });
}

// MV3 规则：事件监听器必须在顶层同步注册。
// 收到 CS 转发的事件后写入 SW 侧 IndexedDB（idb.ts 在 SW 上下文运行，DB 归扩展源），
// 再立即触发 flush；alarms 定时作为兜底。
chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type === EVENT_MSG) {
    void (async () => {
      await putEvent(msg.event as RawEvent);
      await flush();
    })();
  }
  // 未知消息类型不 return true，交由下方录制开关监听器异步响应
});

// 录制开关消息（popup -> SW）：单一 session 由 SW 统一创建/停止，
// 与上方 events-pending 监听并存（两个监听器都会被调用）。
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "START_RECORDING") {
    startRecording(String(msg.note ?? "")).then(sendResponse).catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  if (msg?.type === "STOP_RECORDING") {
    // await 停止流程（内部先做最终上报再清 storage），确保 sendResponse
    // 返回时缓冲事件已尝试上报完毕。
    stopRecording()
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  if (msg?.type === "GET_STATE") {
    getRecordingState().then(sendResponse);
    return true;
  }
});
chrome.alarms.onAlarm.addListener(() => void flush());
void loop();
