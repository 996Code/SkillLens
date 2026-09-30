import { describeElement } from "../shared/describe-element";
import { inputKey } from "../shared/input-key";
import { makePageId } from "../shared/page-id";
import { redactValue } from "../shared/redact";
import { EVENT_MSG } from "../shared/types";
import type { RawEvent } from "../shared/types";
import { collectSnapshot } from "./snapshot";

// 录制门控：初始经 GET_STATE 向 SW 查询（覆盖"已开录的存量页面"场景），
// 之后由 storage.onChanged 跟随 sl_recording 实时更新。录制关：不采集任何事件。
// S42 幂等保护：SW 程序化注入（chrome.scripting）可能对已注入 frame 重复执行
// 本模块——重复注册监听器会产生双份事件，必须挡住。
const w = window as unknown as { __skilllens_cs?: boolean };
if (w.__skilllens_cs) {
  throw new Error("[skilllens] capture already injected");
}
w.__skilllens_cs = true;

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

// S42：动态创建的 about:blank iframe（禅道综合界面等）不会自动注入
// content script——顶层帧发现 iframe 时通知 SW 程序化注入子 frame。
// 幂等由 capture 模块的 __skilllens_cs 守卫保证（重复注入无副作用）。
if (window.top === window) {
  let notifyTimer: ReturnType<typeof setTimeout> | null = null;
  const notifyInject = (): void => {
    if (notifyTimer) return;
    notifyTimer = setTimeout(() => {
      notifyTimer = null;
      if (document.querySelector("iframe")) {
        chrome.runtime.sendMessage({ type: "INJECT_IFRAMES" }).catch(() => {});
      }
    }, 1000);
  };
  notifyInject();
  new MutationObserver(notifyInject).observe(document.documentElement, {
    childList: true, subtree: true,
  });
}

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

// S42：input 事件去抖采集。change 依赖 blur+dirty 标记——程序化填值
// （Playwright fill 不置 dirty）与框架回显覆盖时序下不可靠（若依实测：
// 同一脚本两轮录制，一轮丢 input 步骤导致骨架缺 fill）。input 事件是
// 值变更的可靠信号：600ms 去抖后发一次终值；change 与近期 input 同元素
// 同值时去重；点击/提交锚点前同步 flush（保证 input 先于锚点事件顺序）。
const INPUT_DEBOUNCE_MS = 600;

/** S42-10：隐藏/开关型输入判定（借鉴 Browser-Use 可见性检测）——
 * type=hidden/checkbox/radio + CSS 隐藏（display:none/visibility:hidden）。
 * offsetParent 在 jsdom 恒 null（无布局）不可用。 */
function isHiddenOrSwitchInput(target: HTMLInputElement): boolean {
  if (target.type === "hidden" || target.type === "checkbox" || target.type === "radio") {
    return true;
  }
  try {
    const cs = getComputedStyle(target);
    return cs.display === "none" || cs.visibility === "hidden";
  } catch {
    return false;
  }
}

/** S42-12：picker 组件容器内的承载控件（zui pick-value select 等）——
 * 其值由组件 UI 交互（点击菜单项）程序化同步，input/change 事件是
 * 框架派发的噪声（值已由前置 click 步覆盖，重复 input 步会让回放
 * fill 隐藏 select 必抛错）。 */
function isPickerHostControl(target: Element): boolean {
  return !!target.closest(".picker, .ant-select, [class*=picker], [class*=select]");
}

/** S42-12：change 通道专用——picker/select 组件容器内的 input 一律视为
 * 程序管理值（禅道实测 resolution/resolvedBuild 经 change 通道泄漏）。
 * input 通道不套用此过滤：input 事件只在真实键入时触发（程序赋值
 * el.value 不触发），zui 日期控件的可键入 input 在 .pick.date-picker
 * 容器内，套用会把"计划完成"等用户直填字段整步丢掉（录制学不到
 * 日期步骤 → 回放必被服务端必填校验拦截）。 */
function isProgrammaticInput(target: HTMLInputElement): boolean {
  if (isHiddenOrSwitchInput(target)) return true;
  return isPickerHostControl(target);
}
const INPUT_DEDUP_MS = 2000;
const inputTimers = new Map<HTMLInputElement, ReturnType<typeof setTimeout>>();
const lastInputEmit = new Map<HTMLInputElement, { ts: number; value: string }>();

function emitInputAction(target: HTMLInputElement): void {
  const key = inputKey(target);
  if (!key) return;
  const value = target.type === "password" ? "[REDACTED]" : target.value;
  const now = Date.now();
  const last = lastInputEmit.get(target);
  lastInputEmit.set(target, { ts: now, value });
  if (last && last.value === value && now - last.ts < 500) return;
  void emit("action", {
    type: "input",
    target: describeElement(target),
    name: key,
    value: redactValue(key, value),
  });
}

function flushPendingInputs(): void {
  for (const [el, t] of inputTimers) {
    clearTimeout(t);
    inputTimers.delete(el);
    emitInputAction(el);
  }
}

document.addEventListener(
  "input",
  (e) => {
    const target = e.target as HTMLInputElement;
    if (!target || !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;
    // S42-12：input 通道只滤隐藏/开关型——input 事件仅真实键入触发，
    // picker 容器内的可见输入（zui 日期控件）是用户直填字段须采集；
    // 但 picker 承载 select（pick-value）是组件程序化同步，须滤
    if (target instanceof HTMLInputElement && isHiddenOrSwitchInput(target)) return;
    if (target.tagName === "SELECT" && isPickerHostControl(target)) return;
    const t = inputTimers.get(target);
    if (t) clearTimeout(t);
    inputTimers.set(target, setTimeout(() => {
      inputTimers.delete(target);
      emitInputAction(target);
    }, INPUT_DEBOUNCE_MS));
  },
  { capture: true },
);

document.addEventListener(
  "change",
  (e) => {
    const target = e.target as HTMLInputElement;
    if (!target) return;
    // S42-12：change 通道保持严过滤（含 picker 容器）——
    // 禅道实测：resolution/resolvedBuild 经 change 通道泄漏。
    // 注意不取消挂起的 input 去抖：fill+Enter（zui 日期控件）会先发
    // input 再由框架派发 change，取消会把真实键入整步丢掉
    if (target instanceof HTMLInputElement && isProgrammaticInput(target)) {
      return;
    }
    if (target.tagName === "SELECT" && isPickerHostControl(target)) return;
    // 挂起的 input 去抖由 change 收口（blur 即终值时刻）
    const t = inputTimers.get(target);
    if (t) {
      clearTimeout(t);
      inputTimers.delete(target);
    }
    // 近期 input 已发同值 → 去重（真实键入 blur 不双发）
    const last = lastInputEmit.get(target);
    if (last && last.value === (target.type === "password" ? "[REDACTED]" : target.value)
        && Date.now() - last.ts < INPUT_DEDUP_MS) {
      return;
    }
    // njmind 等低代码设计器的输入框没有 name 属性，
    // 依次回退到 id / placeholder / aria-label，仍取不到则放弃采集。
    const key = inputKey(target);
    if (!key) return;
    const value = target.type === "password" ? "[REDACTED]" : target.value;
    lastInputEmit.set(target, { ts: Date.now(), value });
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
  "click",
  (e) => {
    const target = e.target as Element;
    if (!target) return;
    flushPendingInputs();
    emitSnapshotsAroundAnchor();
    void emit("action", { type: "click", target: describeElement(target), url: location.href });
  },
  { capture: true },
);

document.addEventListener(
  "submit",
  (e) => {
    flushPendingInputs();
    emitSnapshotsAroundAnchor();
    // S35：描述提交按钮（e.submitter）而非 form——form 的 textContent
    // 含内联脚本，label 被污染且无法用于回放定位
    const el = (e as SubmitEvent).submitter ?? (e.target as Element);
    void emit("action", { type: "submit", target: describeElement(el), url: location.href });
  },
  { capture: true },
);

// page-load 需等初始状态就绪后再判定，避免"已开录的存量页面"在 GET_STATE
// 返回前误判为未录制而丢掉首条 navigation 事件。
// S42 all_frames：仅顶层帧发 navigation——iframe（含 about:blank 综合界面）
// 的 page-load 是重复/噪声，且会污染目标系统派生（首条 navigation URL）。
void refreshState().then(() => {
  if (recording && window.top === window) {
    void emit("navigation", { type: "page-load", url: location.href, title: document.title });
  }
});

// 注入 MAIN world 脚本
const s = document.createElement("script");
s.src = chrome.runtime.getURL("src/injected/net-hook.js");
s.async = false;
document.documentElement.appendChild(s);

// 接收网络事件
// S42-12：附带 pageUrl（发出页面）——录制期间其他标签页的后台轮询会带
// 活跃 session_id 混入事件流，服务端按 pageUrl 与锚点页面跨源过滤
window.addEventListener("message", (e) => {
  if (e.source !== window || e.data?.source !== "skilllens-net") return;
  void emit("network", { ...e.data.detail, pageUrl: location.href });
});
