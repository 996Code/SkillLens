// 标记为 ES module：避免顶层 const 与 DOM 全局冲突
// AG3：技能列表直调 executor 模块（popup 只做选择+跳转 executor tab）
import { listExecutorSkills } from "./background/executor";
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

async function loadSkills(): Promise<void> {
  try {
    const skills = await listExecutorSkills();
    renderSkills(Array.isArray(skills) ? skills.slice(0, 20) : []);
  } catch (e: any) {
    const div = document.createElement("div");
    div.style.color = "var(--muted)";
    div.style.fontSize = "12px";
    div.textContent = e.message;
    execList.replaceChildren(div);
  }
}

function renderSkills(skills: any[]): void {
  execList.innerHTML = "";
  if (!skills.length) {
    execList.innerHTML = '<div style="color: var(--muted); font-size: 12px">无技能（先在工作台学习）</div>';
    return;
  }
  // 按系统分组（UX 整改 ②：分类展示）
  const groups = new Map<string, any[]>();
  for (const s of skills) {
    const sys = s.system || "通用";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  for (const [sys, items] of groups) {
    const h = document.createElement("div");
    h.textContent = sys;
    h.style.cssText = "margin:8px 0 2px; font-size:11px; color:var(--muted); font-weight:600";
    execList.append(h);
    for (const s of items) {
      const row = document.createElement("div");
      row.style.cssText = "display:flex; align-items:center; gap:6px; padding:4px 0; border-bottom:1px solid var(--line)";
      const name = document.createElement("span");
      name.style.cssText = "flex:1; font-size:12px";
      name.textContent = `${s.name}${s.requires_confirmation ? " ✎" : ""}`;
      const btn = document.createElement("button");
      btn.textContent = "自动执行";
      btn.style.cssText = "font-size:12px; padding:2px 10px";
      btn.addEventListener("click", () => {
        chrome.tabs.create({ url: `executor.html?skill=${s.id}` });
        window.close();
      });
      row.append(name, btn);
      execList.append(row);
    }
  }
}

void loadSkills();
