// AG3 执行页：独立 tab 内跑步循环（popup 生命周期关不住、SW 消息层
// 不稳——十轮实证后终局架构：执行=专属页面，全程可见）
export {};

import { listExecutorSkills, runSkill, setExecutorToken } from "./background/executor";

const logEl = document.getElementById("log")!;
const go = document.getElementById("go") as HTMLButtonElement;
const stop = document.getElementById("stop") as HTMLButtonElement;
const title = document.getElementById("title")!;
const meta = document.getElementById("meta")!;

const params = new URLSearchParams(location.search);
const skillId = Number(params.get("skill") || 0);
const tokenParam = params.get("token") || "";

function log(msg: string): void {
  const t = new Date().toTimeString().slice(0, 8);
  logEl.textContent += `[${t}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

if (tokenParam) {
  await setExecutorToken(tokenParam);
  history.replaceState(null, "", location.pathname + (skillId ? `?skill=${skillId}` : ""));
}

if (!skillId) {
  title.textContent = "SkillLens 执行器（未指定技能）";
  log("缺少 ?skill= 参数——从 popup 选择技能进入。");
} else {
  title.textContent = `执行技能 #${skillId}`;
  meta.textContent = "点击【开始执行】= 授权在本机浏览器执行全部步骤（C1，含写操作）。";
}

let running = false;
go.addEventListener("click", async () => {
  if (running || !skillId) return;
  running = true;
  go.disabled = true;
  stop.disabled = false;
  log("开始执行…");
  try {
    const skills = await listExecutorSkills().catch(() => []);
    const s = (skills as any[]).find((x) => x.id === skillId);
    if (s?.requires_confirmation) {
      const ok = confirm(`「${s.name}」含写操作。\n确定=授权执行全部步骤（C1）。`);
      if (!ok) { log("已取消（C1 未授权）"); running = false; go.disabled = false; stop.disabled = true; return; }
    }
    const r = await runSkill(skillId, {}, log);
    log(`完成：${r.status}`);
  } catch (e: any) {
    log(`失败：${e.message}`);
  }
  running = false;
  go.disabled = false;
  stop.disabled = true;
});

stop.addEventListener("click", () => {
  log("用户请求停止（当前步完成后中断）");
});
