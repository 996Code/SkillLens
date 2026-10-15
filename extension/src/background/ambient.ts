// AP1 常驻采集（零仪式录制第一片）：
//   SW 监听活动 tab 导航——URL 命中任一 adapter url_matches（白名单制，
//   非全网录）→ 自动开录（source=ambient，C2 分轨）；离开接管站 → 停录。
//   用户显式开录（popup=real_traffic / auto_record=demo）优先：ambient
//   不覆盖、也不越权停止用户会话（sl_ambient 标记区分归属）。
//
// 语义：录制跟随**活动 tab**（单会话模型——sl_recording 全局单旗）。
// 信任边界：仅在已声明接管的系统域录（/adapters/match 白名单）。
import { AGENT_URL } from "../shared/types";
import { getToken } from "./executor";
import { getRecordingState, startRecording, stopRecording } from "./session";

// match 结果缓存（host 级——同站导航不重复请求）
const matchCache = new Map<string, string | null>();
const MATCH_TTL = 10 * 60 * 1000;
const cacheAt = new Map<string, number>();

async function matchAdapter(url: string): Promise<string | null> {
  try {
    const host = new URL(url).host;
    const now = Date.now();
    if (matchCache.has(host) && now - (cacheAt.get(host) ?? 0) < MATCH_TTL) {
      return matchCache.get(host) ?? null;
    }
    const t = await getToken();
    const m = await Promise.race([
      fetch(`${AGENT_URL}/adapters/match?url=${encodeURIComponent(url)}`,
        { headers: { Authorization: `Bearer ${t}` } }),
      new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error("match timeout")), 5000)),
    ]) as Response;
    let hit: string | null = null;
    if (m.ok) {
      const body = await m.json();
      hit = body.adapter_id ?? null;
    }
    matchCache.set(host, hit);
    cacheAt.set(host, now);
    return hit;
  } catch {
    return null;  // 配对失败不开录（fail-closed——信任边界优先）
  }
}

let ambientBusy = false;

async function trace(step: string, detail: string = ""): Promise<void> {
  try {
    const { sl_ambient_debug } = await chrome.storage.local.get("sl_ambient_debug");
    const lines = (Array.isArray(sl_ambient_debug) ? sl_ambient_debug : [])
      .concat(`[${new Date().toTimeString().slice(0, 8)}] ${step} ${detail}`)
      .slice(-20);
    await chrome.storage.local.set({ sl_ambient_debug: lines });
  } catch { /* 调试痕迹失败静默 */ }
}

/** 活动页 URL → ambient 录制决策（幂等；用户显式录制优先）。 */
export async function reconcileAmbient(activeUrl: string | undefined): Promise<void> {
  if (ambientBusy) { await trace("busy-skip"); return; }
  ambientBusy = true;
  try {
    const st = await getRecordingState();
    const isAmbient = (await chrome.storage.local.get("sl_ambient"))
      .sl_ambient === true;
    const onManagedSite = !!activeUrl?.startsWith("http")
      && !!(await matchAdapter(activeUrl));
    await trace("eval", `url=${(activeUrl || "").slice(0, 40)} managed=${onManagedSite} rec=${st.recording} amb=${isAmbient}`);

    if (onManagedSite && !st.recording) {
      // 打开接管站 → 自动开录（ambient 源）
      await startRecording("(ambient 自动录制)", "ambient");
      await chrome.storage.local.set({ sl_ambient: true });
      await trace("started");
      return;
    }
    if (!onManagedSite && st.recording && isAmbient) {
      // 离开接管站 → 停 ambient 录制（用户显式会话不动）
      await stopRecording();
      await chrome.storage.local.remove("sl_ambient");
      await trace("stopped");
    }
  } catch (e) {
    await trace("error", String(e).slice(0, 120));
  } finally {
    ambientBusy = false;
  }
}

/** AP1 入口注册（SW 顶层调用一次）。 */
export function initAmbient(): void {
  chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
    if (info.status === "complete" && tab.active) {
      void reconcileAmbient(tab.url);
    }
  });
  chrome.tabs.onActivated.addListener(({ tabId }) => {
    void chrome.tabs.get(tabId).then((tab) => {
      void reconcileAmbient(tab.url);
    }).catch(() => { /* tab 已关 */ });
  });
  chrome.tabs.onRemoved.addListener(() => {
    // 关 tab 后以当前活动页重判
    void chrome.tabs.query({ active: true, currentWindow: true })
      .then(([t]) => reconcileAmbient(t?.url))
      .catch(() => {});
  });
}
