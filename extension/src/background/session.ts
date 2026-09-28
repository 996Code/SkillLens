import { AGENT_URL } from "../shared/types";
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
  // popup 用户手动开录 = 真实用户流量（S10 C2 标记）；auto_record 经消息显式传 demo
  const res = await fetch(`${AGENT_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_system: "njmind", note, source }),
  });
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
