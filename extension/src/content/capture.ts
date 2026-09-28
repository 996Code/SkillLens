import { describeElement } from "../shared/describe-element";
import { inputKey } from "../shared/input-key";
import { makePageId } from "../shared/page-id";
import { redactValue } from "../shared/redact";
import { EVENT_MSG } from "../shared/types";
import type { RawEvent } from "../shared/types";
import { collectSnapshot } from "./snapshot";

// 录制门控：初始经 GET_STATE 向 SW 查询（覆盖"已开录的存量页面"场景），
// 之后由 storage.onChanged 跟随 sl_recording 实时更新。录制关：不采集任何事件。
let recording = false;

let seq = 0;
function nextSeq(): number {
  return seq++;
}

async function refreshState(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" }).catch(() => null);
  const next = st?.recording === true;
  if (next !== recording) {
    recording = next;
    console.debug("[skilllens] recording =", recording);
  }
}
void refreshState();
chrome.storage.onChanged.addListener((changes, area) => {
  // MV3 SW 状态持久化：从 session 改为 local（S31 修复——SW 重启不丢录制状态）
  if (area === "local" && changes.sl_recording) {
    const next = changes.sl_recording.newValue === true;
    if (next !== recording) {
      recording = next;
      console.debug("[skilllens] recording =", recording);
    }
  }
});
// 兜底轮询：门控原本依赖一次性 GET_STATE + storage.onChanged，
// 任一环失效（SW 重启未广播、storage 事件丢失等）则全程静默不采集。
// 页面生命周期内 3s 轮询一次，开销可忽略。
setInterval(() => void refreshState(), 3000);

async function emit(kind: RawEvent["kind"], payload: Record<string, unknown>): Promise<void> {
  if (!recording) return;
  const event: RawEvent = {
    seq: nextSeq(), page_id: makePageId(), ts: Date.now(), kind,
    payload: { ...payload, __session_id: "" },
  };
  // MV3：content script 与 service worker 不共享 IndexedDB（CS 写的是页面源 DB，
  // SW 读的是扩展源 DB），因此事件经 runtime 消息转发给 SW 落库。
  // fire-and-forget：SW 休眠等异常由 catch 吞掉，事件由 alarms 定时兜底补传。
  // __session_id 统一置空，由 flush（T8）回填 SW 侧 session。
  chrome.runtime.sendMessage({ type: EVENT_MSG, event }).catch(() => {});
}

// 锚点动作前后 UI 状态快照（Sprint 8 块B，kind="snapshot" 走既有事件通道）：
// before——锚点动作事件 enqueue 前同步采集，seq 先于 action 事件；
// after——CS 侧无网络空闲窗口状态（窗口划分在 server 侧 windows.py），
// 退而在锚点后 2.5s（IDLE_MS 2s + 网络尾延迟余量）定时采集。
// 防重入：pendingAfter 计数保证每锚点恰好一个定时器，连点风暴下封顶 8 个挂起。
const AFTER_SNAPSHOT_MS = 2500;
let pendingAfter = 0;

function emitSnapshotsAroundAnchor(): void {
  void emit("snapshot", { ...collectSnapshot(document, "before") });
  if (pendingAfter >= 8) return;
  pendingAfter++;
  setTimeout(() => {
    pendingAfter--;
    void emit("snapshot", { ...collectSnapshot(document, "after") });
  }, AFTER_SNAPSHOT_MS);
}

document.addEventListener(
  "click",
  (e) => {
    const target = e.target as Element;
    if (!target) return;
    emitSnapshotsAroundAnchor();
    void emit("action", { type: "click", target: describeElement(target), url: location.href });
  },
  { capture: true },
);

document.addEventListener(
  "change",
  (e) => {
    const target = e.target as HTMLInputElement;
    if (!target) return;
    // njmind 等低代码设计器的输入框没有 name 属性，
    // 依次回退到 id / placeholder / aria-label，仍取不到则放弃采集。
    const key = inputKey(target);
    if (!key) return;
    const value = target.type === "password" ? "[REDACTED]" : target.value;
    void emit("action", {
      type: "input",
      target: describeElement(target),
      name: key,
      value: redactValue(key, value),
    });
  },
  { capture: true },
);

document.addEventListener(
  "submit",
  (e) => {
    emitSnapshotsAroundAnchor();
    void emit("action", { type: "submit", target: describeElement(e.target as Element), url: location.href });
  },
  { capture: true },
);

// page-load 需等初始状态就绪后再判定，避免"已开录的存量页面"在 GET_STATE
// 返回前误判为未录制而丢掉首条 navigation 事件。
void refreshState().then(() => {
  if (recording) void emit("navigation", { type: "page-load", url: location.href, title: document.title });
});

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
