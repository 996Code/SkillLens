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

function render(recording: boolean, noteText: string, sessionId: string | null,
                counts?: Record<string, number>): void {
  status.textContent = recording ? "录制中" : "未录制";
  wrap.classList.toggle("rec", recording);
  dot.classList.toggle("rec", recording);
  if (recording) {
    const parts = Object.entries(counts ?? {})
      .map(([k, v]) => `${k} ${v}`).join(" · ");
    meta.textContent = `${noteText || "(未命名)"} · ${sessionId ? sessionId.slice(0, 8) : ""}`
      + (parts ? ` · 已捕获 ${parts}` : "");
  } else {
    meta.textContent = "";
  }
}

async function refresh(): Promise<void> {
  const st = await chrome.runtime.sendMessage({ type: "GET_STATE" });
  render(!!st?.recording, st?.note ?? "", st?.sessionId ?? null, st?.counts);
  renderLearnCard();
}

// AI1 学习结果通知卡：停录自动学习的产出/失败在此可见（失败也是信息——
// C3 不吞，用户知道该去工作台人工处理）
async function renderLearnCard(): Promise<void> {
  const card = document.getElementById("learn-card")!;
  const title = document.getElementById("learn-title")!;
  const metaEl = document.getElementById("learn-meta")!;
  const runBtn = document.getElementById("learn-run") as HTMLButtonElement;
  const dismiss = document.getElementById("learn-dismiss")!;
  // 待学会话消费：popup 打开=用户停录后回看。学习进程放独立 learn.html
  // 标签页（页面上下文 fetch 生命周期稳定——SW fire-and-forget 被 CDP
  // 托管浏览器静默吞，多轮验收实锤；popup 自身生命周期太短也不可靠）
  try {
    const { sl_pending_learn: p } = await chrome.storage.local.get("sl_pending_learn") as {
      sl_pending_learn?: { sid: string; at: number } | null;
    };
    if (p?.sid && Date.now() - p.at < 30 * 60 * 1000) {
      await chrome.storage.local.remove("sl_pending_learn");
      chrome.tabs.create({ url: `learn.html?sid=${encodeURIComponent(p.sid)}` });
      window.close();
    }
  } catch { /* 消费失败不阻塞 popup */ }
  try {
    const { sl_last_learn: r } = await chrome.storage.local.get("sl_last_learn") as {
      sl_last_learn?: { status: string; skillId?: number; skillName?: string; error?: string; step?: string; ts: number };
    };
    if (!r) return;
    card.style.display = "block";
    if (r.status === "done") {
      title.textContent = `学习完成：${r.skillName ?? "新技能"}`;
      title.style.color = "var(--ok)";
      metaEl.textContent = `技能 #${r.skillId} 已可执行（停录自动学习）`;
      runBtn.style.display = "";
      runBtn.onclick = () => {
        chrome.tabs.create({ url: `executor.html?skill=${r.skillId}` });
        window.close();
      };
    } else if (r.status === "error") {
      title.textContent = "自动学习失败";
      title.style.color = "var(--danger)";
      metaEl.textContent = `${r.step ? `阶段 ${r.step} ` : ""}${r.error ?? ""}——可到工作台手动处理`;
      runBtn.style.display = "none";
    } else {
      title.textContent = "正在学习刚才的录制…";
      title.style.color = "var(--muted)";
      metaEl.textContent = "完成后这里会更新（也可稍后重开弹窗查看）";
      runBtn.style.display = "none";
    }
    dismiss.onclick = () => {
      card.style.display = "none";
      void chrome.storage.local.remove("sl_last_learn");
    };
  } catch { /* 通知失败不阻塞 popup */ }
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

// AH4b 空间入口：悬浮面板（油猴式）注入当前活动业务页。面板 CS 已常驻
// （manifest），此处只派发唤起事件（executeScript func 注入——
// executeScript files 引 TS 源不编译，实锤失败；func 总是可用）
document.getElementById("open-space")!.addEventListener("click", async () => {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const biz = tabs.find((t) => (t.url || "").startsWith("http")
      && !(t.url || "").startsWith("chrome-extension://"));
    if (biz?.id) {
      await chrome.scripting.executeScript({
        target: { tabId: biz.id },
        func: () => window.dispatchEvent(new CustomEvent("skilllens:show-space")),
      });
    }
    // 不显式 window.close()：executeScript 回调与 popup 卸载的竞态会砍掉
    // 注入（真机两轮实锤 MISSING）——popup 失焦自动关（浏览器原生行为），
    // 注入链稳定完成后 UI 自然消失
  } catch { /* 注入失败不阻塞 */ }
});

void loadSkills();
