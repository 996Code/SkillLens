import { AGENT_URL } from "../shared/types";

export interface RecordingState {
  recording: boolean;
  sessionId: string | null;
  note: string;
}

export async function startRecording(note: string): Promise<{ id: string }> {
  const res = await fetch(`${AGENT_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_system: "njmind", note }),
  });
  if (!res.ok) throw new Error(`create session failed: ${res.status}`);
  const session = await res.json();
  await chrome.storage.session.set({
    sl_recording: true,
    sl_session: session.session_id,
    sl_note: note,
  });
  return { id: session.session_id };
}

export async function stopRecording(): Promise<void> {
  await chrome.storage.session.remove(["sl_recording", "sl_session", "sl_note"]);
}

export async function getRecordingState(): Promise<RecordingState> {
  const st = await chrome.storage.session.get(["sl_recording", "sl_session", "sl_note"]);
  return {
    recording: st.sl_recording === true,
    sessionId: (st.sl_session as string) ?? null,
    note: (st.sl_note as string) ?? "",
  };
}
