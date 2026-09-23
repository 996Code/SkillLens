import { describeElement } from "../shared/describe-element";
import { redactValue } from "../shared/redact";
import { AGENT_URL, EVENT_MSG } from "../shared/types";
import type { RawEvent } from "../shared/types";

let seq = 0;
let sessionId = "";

async function ensureSession(): Promise<void> {
  if (sessionId) return;
  const resp = await fetch(`${AGENT_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_system: location.host, note: "auto" }),
  });
  sessionId = (await resp.json()).session_id;
}

async function emit(kind: RawEvent["kind"], payload: Record<string, unknown>): Promise<void> {
  await ensureSession();
  const event: RawEvent = {
    seq: seq++, ts: Date.now(), kind,
    payload: { ...payload, __session_id: sessionId },
  };
  // MV3：content script 与 service worker 不共享 IndexedDB（CS 写的是页面源 DB，
  // SW 读的是扩展源 DB），因此事件经 runtime 消息转发给 SW 落库。
  // fire-and-forget：SW 休眠等异常由 catch 吞掉，事件由 alarms 定时兜底补传。
  chrome.runtime.sendMessage({ type: EVENT_MSG, event }).catch(() => {});
}

document.addEventListener(
  "click",
  (e) => {
    const target = e.target as Element;
    if (!target) return;
    void emit("action", { type: "click", target: describeElement(target), url: location.href });
  },
  { capture: true },
);

document.addEventListener(
  "change",
  (e) => {
    const target = e.target as HTMLInputElement;
    if (!target?.name) return;
    const value = target.type === "password" ? "[REDACTED]" : target.value;
    void emit("action", {
      type: "input",
      target: describeElement(target),
      name: target.name,
      value: redactValue(target.name, value),
    });
  },
  { capture: true },
);

document.addEventListener(
  "submit",
  (e) => {
    void emit("action", { type: "submit", target: describeElement(e.target as Element), url: location.href });
  },
  { capture: true },
);

void emit("navigation", { type: "page-load", url: location.href, title: document.title });

// 注入 MAIN world 脚本
const s = document.createElement("script");
s.src = chrome.runtime.getURL("src/injected/net-hook.js");
s.async = false;
document.documentElement.appendChild(s);

// 接收网络事件
window.addEventListener("message", (e) => {
  if (e.source !== window || e.data?.source !== "skilllens-net") return;
  void emit("network", e.data.detail);
});
