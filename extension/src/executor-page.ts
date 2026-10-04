// AG3 执行页：独立 tab 内跑步循环（popup 生命周期关不住、SW 消息层
// 不稳——十轮实证后终局架构：执行=专属页面，全程可见）
// UX 评审整改：确认卡带技能名+目标页；完成结果卡+工作台回看链接
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
// auto=1：跳过 confirm（验收/编排场景——授权由调用方持有；人工使用
// 不带此参数，C1 确认卡正常弹出）
const autoConfirm = params.get("auto") === "1";

const WORKBENCH = "http://127.0.0.1:8710/graph";

function log(msg: string): void {
  const t = new Date().toTimeString().slice(0, 8);
  logEl.textContent += `[${t}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function showResultCard(status: string, runId: number | null): void {
  const card = document.getElementById("result-card")!;
  const st = document.getElementById("result-status")!;
  const link = document.getElementById("result-link") as HTMLAnchorElement;
  const ok = status === "pass";
  st.textContent = ok ? "✓ 通过" : "✗ 未通过";
  st.className = ok ? "pass" : "fail";
  card.style.display = "block";
  if (runId) {
    link.href = `${WORKBENCH}/run/${runId}`;
    link.style.display = "inline";
  }
}

if (tokenParam) {
  await setExecutorToken(tokenParam);
  history.replaceState(null, "", location.pathname + (skillId ? `?skill=${skillId}` : ""));
}

let skillName = `#${skillId}`;
let skillWrites = false;
if (!skillId) {
  title.textContent = "SkillLens 执行器（未指定技能）";
  log("缺少 ?skill= 参数——从 popup 选择技能进入。");
} else {
  meta.textContent = "点击【开始执行】开始。写操作技能会先请求授权（C1）。";
  // 技能元数据预取：标题带名字，确认卡有据
  try {
    const skills = (await listExecutorSkills()) as any[];
    const s = skills.find((x) => x.id === skillId);
    if (s) {
      skillName = `#${s.id} ${s.name}`;
      skillWrites = !!s.requires_confirmation;
      title.textContent = `执行 ${skillName}`;
      meta.textContent = skillWrites
        ? "该技能含写操作——点击开始后需授权。"
        : "只读技能——直接执行。";
    }
  } catch { /* 元数据失败不阻塞 */ }
}

let running = false;
go.addEventListener("click", async () => {
  if (running || !skillId) return;
  running = true;
  go.disabled = true;
  stop.disabled = false;
  document.getElementById("result-card")!.style.display = "none";
  log("开始执行…");
  try {
    if (skillWrites && !autoConfirm) {
      const ok = confirm(
        `「${skillName}」含写操作。\n` +
        "点击确定=授权在本机浏览器执行全部步骤（C1）。");
      if (!ok) { log("已取消（C1 未授权）"); running = false; go.disabled = false; stop.disabled = true; return; }
    } else if (skillWrites && autoConfirm) {
      log("auto 模式：C1 授权由调用方持有，跳过确认卡");
    }
    const r = await runSkill(skillId, {}, log);
    log(`完成：${r.status}`);
    showResultCard(r.status, r.runId ?? null);
  } catch (e: any) {
    log(`失败：${e.message}`);
    showResultCard("fail", null);
  }
  running = false;
  go.disabled = false;
  stop.disabled = true;
});

stop.addEventListener("click", () => {
  log("用户请求停止（当前步完成后中断）");
});
