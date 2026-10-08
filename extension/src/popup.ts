// 标记为 ES module：避免顶层 const 与 DOM 全局冲突
// AG3：技能列表直调 executor 模块（popup 只做选择+跳转 executor tab）
import { listExecutorSkills } from "./background/executor";
import { buildHint, renderSkillsInto } from "./popup-render";
export {};

const note = document.getElementById("note") as HTMLInputElement;
const status = document.getElementById("status")!;
const wrap = document.getElementById("status-wrap")!;
const dot = document.getElementById("status-dot")!;
const meta = document.getElementById("meta")!;
const conn = document.getElementById("conn")!;
const connText = document.getElementById("conn-text")!;

function render(recording: boolean, noteText: string, sessionId: string | null): void {
  status.textContent = recording ? "录制中" : "未录制";
  wrap.classList.toggle("rec", recording);
  dot.classList.toggle("rec", recording);
  meta.textContent = recording
    ? `${noteText || "(未命名)"} · ${sessionId ? sessionId.slice(0, 8) : ""}`
    : "";
}

async function refresh(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  render(!!st?.recording, st?.note ?? "", st?.sessionId ?? null);
}

// 连接探测：直连 Agent health（失败不阻塞录制流程，只显红点）
async function probe(): Promise<void> {
  try {
    const { AGENT_URL } = await import("./shared/types");
    const res = await fetch(`${AGENT_URL}/health`);
    connText.textContent = res.ok ? "Agent 已连接" : "Agent 异常";
    conn.classList.toggle("ok", res.ok);
    conn.classList.toggle("err", !res.ok);
  } catch {
    connText.textContent = "Agent 未连接（检查 8710）";
    conn.classList.add("err");
  }
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
void probe();

// AG3：执行在独立 executor tab（popup 生命周期关不住执行循环——
// 实证：导航发生即 popup 被冻结）。popup 只做选择+跳转。
const execList = document.getElementById("exec-list")!;
const searchBox = document.getElementById("exec-search") as HTMLInputElement | null;

let allSkills: any[] = [];

async function loadSkills(): Promise<void> {
  try {
    const skills = await listExecutorSkills();
    allSkills = Array.isArray(skills) ? skills : [];
    renderSkillsInto(execList, allSkills, searchBox?.value || "", (id) => {
      chrome.tabs.create({ url: `executor.html?skill=${Number(id)}` });
      window.close();
    });
  } catch (e: any) {
    // 401/超时的自助指引：工作台登录本身不会把 token 配给插件
    // （写入只发生在 executor.html?token= 打开时）
    execList.textContent = buildHint(e?.message || String(e));
  }
}

function renderSkills(): void {
  renderSkillsInto(execList, allSkills, searchBox?.value || "", (id) => {
    chrome.tabs.create({ url: `executor.html?skill=${Number(id)}` });
    window.close();
  });
}

searchBox?.addEventListener("input", () => renderSkills());

void loadSkills();
