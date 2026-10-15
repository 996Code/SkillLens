import { putEvent, takeEvents } from "../store/idb";
import { AGENT_URL, EVENT_MSG } from "../shared/types";
import type { RawEvent } from "../shared/types";
import { assignSession } from "../shared/assign-session";
import { getRecordingState, startRecording, stopRecording } from "./session";
import { listExecutorSkills, runScenario, runSkill } from "./executor";
import { autoLearn } from "./learn";

// S31 修复：录制状态已从 chrome.storage.session 改为 chrome.storage.local
// （MV3 SW 空闲被杀后 session 存储丢失，local 持久化跨 SW 重启）。
// chrome.storage.local 对 content script 默认可读，无需 setAccessLevel。

const BATCH = 50;
const MAX_RETRIES = 3;

// 内存重试计数（POC：service worker 重启即清零；Sprint 1 改为持久重试队列）
const retries = new Map<string, number>();

function eventKey(e: RawEvent): string {
  // page_id 必入键（评审 #14）：不同 frame 同毫秒同类型事件键碰撞会
  // 互相污染重试计数导致误丢
  return `${e.ts}:${e.seq}:${e.kind}:${e.pageId ?? ""}`;
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
        // 跨域污染守卫（服务端 events 豁免鉴权——非插件调用方无此头被 403）
        headers: { "Content-Type": "application/json",
                   "X-SkillLens-Agent": "1" },
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

// S42：动态创建的 about:blank iframe 不会自动注入 content script——
// 收到顶层帧的 INJECT_IFRAMES 通知后，程序化注入该 tab 的全部子 frame。
// 重复注入由 capture 模块的 __skilllens_cs 守卫幂等处理。
async function injectFrames(tabId: number): Promise<void> {
  try {
    const frames = await chrome.webNavigation.getAllFrames({ tabId });
    const frameIds = frames.filter((f) => f.frameId !== 0).map((f) => f.frameId);
    const file = chrome.runtime.getManifest().content_scripts?.[0]?.js?.[0];
    if (frameIds.length === 0 || !file) return;
    await chrome.scripting.executeScript({ target: { tabId, frameIds }, files: [file] });
    console.debug("[skilllens] injected into", frameIds.length, "sub frames");
  } catch (err) {
    console.warn("[skilllens] frame inject failed", err);
  }
}

// MV3 规则：事件监听器必须在顶层同步注册。
// 收到 CS 转发的事件后写入 SW 侧 IndexedDB（idb.ts 在 SW 上下文运行，DB 归扩展源），
// 再立即触发 flush；alarms 定时作为兜底。
// AP1 常驻采集：tab 监听在顶层同步注册（SW 冷启动即生效）。
import { initAmbient } from "./ambient";
initAmbient();

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg?.type === EVENT_MSG) {
    void (async () => {
      await putEvent(msg.event as RawEvent);
      // AI1 录制反馈：累计事件计数（popup 实时展示"已捕获 N 项"——
      // 按 kind 分桶，录得对不对当场可见）
      try {
        const k = String((msg.event as RawEvent)?.kind ?? "?");
        const cur = (await chrome.storage.session.get("sl_counts")) as
          Record<string, number> | undefined;
        const counts = cur?.sl_counts ?? {};
        counts[k] = (counts[k] ?? 0) + 1;
        await chrome.storage.session.set({ sl_counts: counts });
      } catch { /* 计数失败不影响上报 */ }
      await flush();
    })();
  }
  if (msg?.type === "INJECT_IFRAMES" && sender.tab?.id != null) {
    void injectFrames(sender.tab.id);
  }
  // 未知消息类型不 return true，交由下方录制开关监听器异步响应
});

// 录制开关消息（popup -> SW）：单一 session 由 SW 统一创建/停止，
// 与上方 events-pending 监听并存（两个监听器都会被调用）。
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "START_RECORDING") {
    // source 透传：popup 不带 → 缺省 real_traffic；auto_record 显式带 demo
    chrome.storage.session.remove("sl_counts").catch(() => {});
    startRecording(String(msg.note ?? ""), String(msg.source ?? "real_traffic"))
      .then(sendResponse)
      .catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  if (msg?.type === "STOP_RECORDING") {
    // 真实根因仍查（storage.local 跨 SW 实例偶发丢失，AI1 验收实锤），但
    // 学习触发改挂进 stopRecording 内部（session.ts 是状态权威——它清理
    // 前一定持有 sid），消息层分支只负责响应。
    stopRecording()
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  if (msg?.type === "GET_STATE") {
    getRecordingState().then(sendResponse);
    return true;
  }
  // AG3：扩展执行器消息面（单一 listener 分发——MV3 多 listener 的
  // sendResponse 竞争会互踩）。静态导入：动态 import 在 SW 冷启动竞态下
  // 会丢 sendResponse（popup 收 undefined）
  if (msg?.type === "EXECUTOR_LIST") {
    listExecutorSkills()
      .then(sendResponse)
      .catch((e) => sendResponse({ error: String(e) }));
    return true;
  }
  // AH6 页内执行：面板发起（sender.tab 即业务页）——执行循环跑在 SW
  // （CDP 命令活动保活），attach 该页签直接驱动；进度经 tabs.sendMessage
  // 回流面板显示。skill/scenario 二选一。
  if (msg?.type === "EXECUTOR_RUN_ON_TAB") {
    if (sender.tab?.id == null) { sendResponse({ error: "no tab" }); return true; }
    sendResponse({ started: true });
    startRunOnTab(sender.tab.id, { skillId: msg.skillId, scenarioId: msg.scenarioId,
                                   overrides: msg.overrides });
    return true;
  }
// AH6 页内执行（双入口：面板消息不可靠时走 storage 事件——CDP 托管浏览器
// content script→SW 的 runtime.sendMessage 实测不通，storage.onChanged 稳定）
let execRunning = false;  // 执行互斥：同 tab 并发 attach 冲突（port 双发实锤）

function startRunOnTab(tabId: number, req: { skillId?: number; scenarioId?: number; overrides?: Record<string, string> }): void {
  if (execRunning) {
    void chrome.tabs.sendMessage(tabId, { type: "SL_PROGRESS",
      msg: "已有执行进行中——请等当前执行结束" }).catch(() => {});
    return;
  }
  execRunning = true;
  const onProgress = (m: string) => {
    void chrome.tabs.sendMessage(tabId, { type: "SL_PROGRESS", msg: m }).catch(() => {});
    void chrome.storage.local.get("sl_exec_log").then(({ sl_exec_log: old }) => {
      const lines = (Array.isArray(old) ? old : []).concat(
        `[${new Date().toTimeString().slice(0, 8)}] ${m}`);
      void chrome.storage.local.set({ sl_exec_log: lines.slice(-200) });
    }).catch(() => {});
  };
  void (async () => {
    try {
      if (req.scenarioId != null) {
        await runScenario(Number(req.scenarioId), onProgress, undefined, tabId);
      } else if (req.skillId != null) {
        await runSkill(Number(req.skillId), req.overrides || {}, onProgress, undefined, tabId);
      }
    } catch (e: any) {
      onProgress(`执行失败：${e?.message ?? e}`);
    } finally {
      execRunning = false;
      // SW 重启丢内存互斥的兜底：storage 持久锁（10 分钟过期防死锁）
      void chrome.storage.local.set({ sl_exec_lock: 0 }).catch(() => {});
    }
  })();
}


// AH6b port 通道：sendMessage 在 CDP 托管环境断，长连接 port 是另一机制
// （面板 connect 后 postMessage 执行请求——同连接回传进度）
chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "skilllens-exec") return;
  // 回执：面板 1.5s 内收到即认为 port 通道活着（CDP 托管环境实测全断——
  // 面板据此自动回退执行页路径；真 Chrome port 直达=无跳板）
  try { port.postMessage({ type: "SL_PONG" }); } catch { /* 断连 */ }
  port.onMessage.addListener((msg: any) => {
    if (msg?.type !== "EXEC_RUN") return;
    // L3 代际新鲜度（generation 精简形态）：EXEC_RUN 带时间戳，过期
    // 请求（SW 重启/port 重放）不执行——与 storage 入口同款语义
    if (msg.at && Date.now() - Number(msg.at) > 10000) {
      port.postMessage({ type: "SL_PROGRESS", msg: "请求已过期（旧会话重放）——已忽略" });
      return;
    }
    const sender = port.sender;
    const tabId = sender?.tab?.id;
    if (tabId == null) { port.postMessage({ type: "SL_PROGRESS", msg: "无页签上下文" }); return; }
    startRunOnTab(tabId, { skillId: msg.skillId, scenarioId: msg.scenarioId,
                           overrides: msg.overrides });
  });
});

// storage 事件入口：面板写 sl_exec_request={skillId|scenarioId}（+时间戳防重复
// 与陈旧过滤）。tabId 由 SW 现取活动业务页（面板发起时其所在页即活动页
// ——面板是 content script 无 chrome.tabs，不能自带）
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.sl_exec_request?.newValue) return;
  const req = changes.sl_exec_request.newValue as {
    at: number; skillId?: number; scenarioId?: number;
    overrides?: Record<string, string> };
  if (Date.now() - (req.at || 0) > 10000) return;  // 陈旧请求忽略
  // SW 重启丢内存互斥的兜底：storage 持久锁（10 分钟过期防死锁）——
  // storage.onChanged 在 SW 重启后可能重复消费近 10s 内的旧请求
  void chrome.storage.local.get("sl_exec_lock").then(({ sl_exec_lock: lock }) => {
    if (lock && Date.now() - Number(lock) < 600000) return;
    void chrome.storage.local.set({ sl_exec_lock: Date.now() }).catch(() => {});
    void (async () => {
      try {
        const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
        const biz = tabs.find((t) => (t.url || "").startsWith("http")
          && !(t.url || "").startsWith("chrome-extension://"));
        if (!biz?.id) return;
        startRunOnTab(biz.id, req);
      } catch { /* 取页失败静默 */ }
    })();
  }).catch(() => {});
});

  if (msg?.type === "EXECUTOR_RUN") {
    // 评审 #13：SW 上下文跑 runSkill 有 MV3 30s 空闲被杀风险（执行循环/
    // networkLog 全丢），且与 executor.html 页路径双入口漂移——统一改开
    // 执行页（AG3 终局架构）。同步 sendResponse（MV3 丢 channel 实证）。
    sendResponse({ started: true });
    const u = new URL(chrome.runtime.getURL("executor.html"));
    u.searchParams.set("skill", String(msg.skillId ?? ""));
    if (msg.overrides && Object.keys(msg.overrides).length) {
      for (const [k, v] of Object.entries(msg.overrides))
        u.searchParams.set(`fill_${k}`, v);
    }
    chrome.tabs.create({ url: u.toString() }).catch(() => {});
  }
});
chrome.alarms.onAlarm.addListener(() => void flush());
void loop();
