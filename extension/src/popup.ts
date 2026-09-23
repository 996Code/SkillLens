// 标记为 ES module：避免顶层 const status 与 DOM 全局 window.status（string）冲突
export {};

const note = document.getElementById("note") as HTMLInputElement;
const status = document.getElementById("status")!;

async function refresh(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  status.textContent = st?.recording
    ? `录制中：${st.note || "(未命名)"} / ${st.sessionId?.slice(0, 8)}`
    : "未录制";
}

document.getElementById("start")!.addEventListener("click", async () => {
  status.textContent = "创建会话…";
  const resp = await chrome.runtime.sendMessage({ type: "START_RECORDING", note: note.value });
  status.textContent = resp?.error ? `失败：${resp.error}` : "已开始录制";
  void refresh();
});

document.getElementById("stop")!.addEventListener("click", async () => {
  await chrome.runtime.sendMessage({ type: "STOP_RECORDING" });
  void refresh();
});

void refresh();
