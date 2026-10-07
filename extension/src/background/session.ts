import { AGENT_URL } from "../shared/types";
import { getToken } from "./executor";
import { finalFlushWithSession } from "./uploader";

export interface RecordingState {
  recording: boolean;
  sessionId: string | null;
  note: string;
}

// MV3 SW 空闲 ~30s 被 Chrome 杀死，chrome.storage.session 随 SW 重启丢失。
// 改用 chrome.storage.local 持久化录制状态——SW 重启后自动恢复，
// content script 的 storage.onChanged 监听同步改 local。
const STORAGE_AREA = "local" as const;

export async function startRecording(
  note: string,
  source: string = "real_traffic",
): Promise<{ id: string }> {
  // popup 用户手动开录 = 真实用户流量（S10 C2 标记）；auto_record 经消息显式传 demo。
  // P2.5 自动隔离：当前活动页 URL → 服务端 url_matches 通配符配对
  // （油猴 @match 语义）——命中 adapter 即以该系统建会话；未命中回退 njmind
  let targetSystem = "njmind";
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url?.startsWith("http")) {
      // /adapters/match 在鉴权守卫后面——必须带 Bearer，否则 401 静默
      // 回退 njmind（评审实锤：P2.5 插件路径配对失效根因）
      const t = await getToken();
      const m = await Promise.race([
        fetch(`${AGENT_URL}/adapters/match?url=${encodeURIComponent(tab.url)}`,
          { headers: { Authorization: `Bearer ${t}` } }),
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error("match timeout")), 5000)),
      ]);
      if (m.ok) {
        const body = await m.json();
        if (body.adapter_id) targetSystem = body.adapter_id;
      }
    }
  } catch { /* 配对失败回退默认——不阻塞录制 */ }
  // 超时保护（评审 #16）：server 挂起时 popup 永久等待——与 executor 同款 race
  const res = await Promise.race([
    fetch(`${AGENT_URL}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 "X-SkillLens-Agent": "1" },
      body: JSON.stringify({ target_system: targetSystem, note, source }),
    }),
    new Promise<never>((_, rej) =>
      setTimeout(() => rej(new Error("create session timeout 30s")), 30000)),
  ]) as Response;
  if (!res.ok) throw new Error(`create session failed: ${res.status}`);
  const session = await res.json();
  await chrome.storage.local.set({
    sl_recording: true,
    sl_session: session.session_id,
    sl_note: note,
  });
  return { id: session.session_id };
}

export async function stopRecording(): Promise<void> {
  // 时序竞态修复：若先清 storage，停止后到达的 flush（alarm/消息驱动）
  // 读到 sessionId 为 null，缓冲事件全进 deferred 永久滞留（session 0 事件）。
  // 因此在清除标记之前，用当前 sid 做一次最终上报兜底。
  const st = await getRecordingState();
  await finalFlushWithSession(st.sessionId);
  await chrome.storage.local.remove(["sl_recording", "sl_session", "sl_note"]);
}

export async function getRecordingState(): Promise<RecordingState> {
  const st = await chrome.storage.local.get(["sl_recording", "sl_session", "sl_note"]);
  return {
    recording: st.sl_recording === true,
    sessionId: (st.sl_session as string) ?? null,
    note: (st.sl_note as string) ?? "",
  };
}
