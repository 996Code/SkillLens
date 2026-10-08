// AH4 空间小窗：右上角独立窗口（popup 按钮打开，带当前 tab URL）。
// 流程：/adapters/match 识别当前系统 → 只显示该系统回放 → 点选组链
// （按点击顺序）→ 保存（POST /chains 纯数据）或立即执行
// （executor.html?chain= 新 tab，整链 C1 在那里）。
export {};

import { api, getToken, listExecutorSkills } from "./background/executor";
import { AGENT_URL } from "./shared/types";

const params = new URLSearchParams(location.search);
const tabUrl = params.get("tab") || "";

const sysEl = document.getElementById("sys")!;
const search = document.getElementById("search") as HTMLInputElement;
const list = document.getElementById("skill-list")!;
const bar = document.getElementById("picked-bar")!;
const pickedSteps = document.getElementById("picked-steps")!;
const chainName = document.getElementById("chain-name") as HTMLInputElement;
const runNow = document.getElementById("run-now") as HTMLButtonElement;
const saveBtn = document.getElementById("save-chain") as HTMLButtonElement;
const savedEl = document.getElementById("saved-chains")!;

let systemName = "";
let allSkills: any[] = [];
let picked: any[] = [];

async function detectSystem(): Promise<void> {
  if (!tabUrl) { sysEl.textContent = "未知来源页"; return; }
  try {
    const t = await getToken();
    const res = await fetch(
      `${AGENT_URL}/adapters/match?url=${encodeURIComponent(tabUrl)}`,
      { headers: { Authorization: `Bearer ${t}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const m = await res.json();
    systemName = m.system || "";
    sysEl.textContent = systemName || `未识别（${m.adapter_id ?? "无匹配"}）`;
    sysEl.classList.toggle("ok", !!systemName);
  } catch (e: any) {
    sysEl.textContent = "识别失败";
  }
}

function renderSkills(): void {
  const q = search.value.trim().toLowerCase();
  list.replaceChildren();
  const visible = q
    ? allSkills.filter((s) => `${s.name}`.toLowerCase().includes(q))
    : allSkills;
  if (!allSkills.length) {
    list.append(muted(systemName ? "该系统暂无回放（先录制学习）" : "无技能"));
    return;
  }
  for (const s of visible) {
    const row = document.createElement("div");
    row.className = "skill-row" + (picked.some((p) => p.id === s.id) ? " picked" : "");
    const ord = document.createElement("span");
    ord.className = "ord";
    const idx = picked.findIndex((p) => p.id === s.id);
    ord.textContent = idx >= 0 ? String(idx + 1) : "";
    const nm = document.createElement("span");
    nm.className = "nm";
    nm.textContent = `${s.name}`;
    if (s.requires_confirmation) {
      const wc = document.createElement("span");
      wc.className = "wc";
      wc.textContent = "写";
      row.append(nm, wc, ord);
    } else {
      row.append(nm, ord);
    }
    row.addEventListener("click", () => togglePick(s));
    list.append(row);
  }
}

function togglePick(s: any): void {
  const idx = picked.findIndex((p) => p.id === s.id);
  if (idx >= 0) picked.splice(idx, 1);
  else picked.push(s);
  bar.style.display = picked.length ? "block" : "none";
  pickedSteps.textContent = picked.length
    ? picked.map((p, i) => `${i + 1}. ${p.name}`).join(" → ")
    : "";
  renderSkills();
}

function muted(text: string): HTMLElement {
  const d = document.createElement("div");
  d.className = "muted";
  d.textContent = text;
  return d;
}

async function loadSkills(): Promise<void> {
  try {
    const skills = await listExecutorSkills();
    allSkills = (Array.isArray(skills) ? skills : [])
      .filter((s: any) => !systemName || (s.system || "") === systemName);
    renderSkills();
  } catch (e: any) {
    list.replaceChildren(muted(`加载失败：${e.message}`));
  }
}

// ---- 保存 / 执行 ----

interface ChainPayload {
  name: string;
  system: string;
  steps: Array<{ skill_id: number; overrides: Record<string, string> }>;
}

function chainPayload(): ChainPayload | null {
  if (!picked.length) return null;
  const name = chainName.value.trim() || `链 ${new Date().toTimeString().slice(0, 5)}`;
  return { name, system: systemName || "通用",
           steps: picked.map((p) => ({ skill_id: p.id, overrides: {} })) };
}

saveBtn.addEventListener("click", async () => {
  const payload = chainPayload();
  if (!payload) return;
  try {
    const r = await api("/chains", { method: "POST", body: JSON.stringify(payload) });
    chainName.value = "";
    picked = [];
    bar.style.display = "none";
    renderSkills();
    await loadChains();
  } catch (e: any) {
    pickedSteps.textContent = `保存失败：${e.message}`;
  }
});

runNow.addEventListener("click", () => {
  const payload = chainPayload();
  if (!payload) return;
  // 立即执行：先保存再开执行页（执行页按 chain id 拉数据——链数据单一来源）
  void (async () => {
    try {
      const r = await api("/chains", { method: "POST", body: JSON.stringify(payload) });
      const id = (r as any).id;
      chrome.tabs.create({ url: `executor.html?chain=${id}` });
      window.close();
    } catch (e: any) {
      pickedSteps.textContent = `失败：${e.message}`;
    }
  })();
});

async function loadChains(): Promise<void> {
  try {
    const chains = await api(`/chains${systemName ? `?system=${encodeURIComponent(systemName)}` : ""}`);
    savedEl.replaceChildren();
    if (!Array.isArray(chains) || !chains.length) {
      savedEl.append(muted("无"));
      return;
    }
    for (const c of chains) {
      const row = document.createElement("div");
      row.className = "chain-row";
      const nm = document.createElement("span");
      nm.className = "nm";
      nm.textContent = c.name;
      const meta = document.createElement("span");
      meta.className = "meta";
      meta.textContent = `${(c.steps || []).length} 步`;
      const run = document.createElement("button");
      run.textContent = "执行";
      run.addEventListener("click", () => {
        chrome.tabs.create({ url: `executor.html?chain=${c.id}` });
        window.close();
      });
      const del = document.createElement("button");
      del.className = "del";
      del.textContent = "删";
      del.addEventListener("click", async () => {
        try { await api(`/chains/${c.id}`, { method: "DELETE" }); await loadChains(); }
        catch (e: any) { meta.textContent = `删除失败：${e.message}`; }
      });
      row.append(nm, meta, run, del);
      savedEl.append(row);
    }
  } catch (e: any) {
    savedEl.replaceChildren(muted(`链加载失败：${e.message}`));
  }
}

search.addEventListener("input", () => renderSkills());

await detectSystem();
await loadSkills();
await loadChains();
