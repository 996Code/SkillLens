// AG3 执行页：独立 tab 内跑步循环（popup 生命周期关不住、SW 消息层
// 不稳——十轮实证后终局架构：执行=专属页面，全程可见）
// UX 评审整改：确认卡带技能名+目标页；完成结果卡+工作台回看链接
// AH3 链模式：?chain=<id> 顺序执行多个技能（整链 C1 一次确认、步进报告、
// fail 即停）——链=服务端纯数据，规则（${unique:}）在本页解释
export {};

import { listExecutorSkills, runSkill, setExecutorToken, api } from "./background/executor";
import { resolveChainSteps } from "./shared/chain-rules";

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
  // UX 评审：日志黑话→白话（用户看不懂 attach/快照/介入）
  const plain = msg
    .replace(/^已 attach（顶部横幅=执行中，全程可见）$/,
             "已连接浏览器（页面顶部的提示条表示执行中）")
    .replace(/^快照（(before|after)）$/,
             (m, p) => p === "before" ? "记录执行前页面状态" : "记录执行后页面状态")
    .replace(/^导航 (.+)$/, (m, u) => `正在打开页面：${u}`)
    .replace(/^导航后实际页面: (.+)$/, (m, u) => `页面已打开：${u.slice(0, 60)}`)
    .replace(/^定位失败：(.+)（触发服务端介入）$/,
             (m, l) => `未找到「${l}」按钮——正在智能重试`)
    .replace(/^复用空白页签执行$/, "准备执行页签")
    .replace(/^中止：(.+)$/, (m, e) => `执行中止：${e}`)
    .replace(/^完成：(.+)$/, (m, s) => `执行结束（${s}）`);
  logEl.textContent += `[${t}] ${plain}\n`;
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
  const keep = chainId ? `?chain=${chainId}` : (skillId ? `?skill=${skillId}` : "");
  history.replaceState(null, "", location.pathname + keep);
}

let skillName = `#${skillId}`;
let skillWrites = false;

// AH3 链模式数据：?chain=<id>（与 ?skill= 互斥，链优先）
const chainId = Number(params.get("chain") || 0);
let chainData: any = null;

if (chainId) {
  // 链模式：拉链数据（含技能概要）——标题/确认卡/步进报告都有据
  try {
    chainData = await api(`/chains/${chainId}`);
    const names = (chainData.steps || [])
      .map((st: any) => `#${st.skill_id} ${st.skill?.name ?? ""}`).join(" → ");
    title.textContent = `链执行 ${chainData.name}`;
    meta.textContent = `${(chainData.steps || []).length} 个步骤：${names}`;
    skillWrites = (chainData.steps || []).some((st: any) => st.skill?.requires_confirmation);
    if (skillWrites) meta.textContent += "（含写操作——点击开始后需授权）";
  } catch (e: any) {
    log(`链加载失败：${e.message}`);
    title.textContent = "链执行（加载失败）";
  }
} else if (!skillId) {
  title.textContent = "SkillLens 执行器（未指定技能）";
  log("缺少 ?skill= 或 ?chain= 参数——从 popup/空间选择进入。");
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
let stopRequested = false;
go.addEventListener("click", async () => {
  if (running || (!skillId && !chainData)) return;
  running = true;
  stopRequested = false;
  go.disabled = true;
  stop.disabled = false;
  document.getElementById("result-card")!.style.display = "none";
  log("开始执行…");
  try {
    if (chainData) {
      // ---- AH3 链执行：整链 C1 一次确认 → 逐步执行 → fail 即停 ----
      const steps = chainData.steps || [];
      if (skillWrites && !autoConfirm) {
        const names = steps.map((st: any) =>
          `#${st.skill_id} ${st.skill?.name ?? ""}`).join("\n  ");
        const ok = confirm(
          `链「${chainData.name}」含写操作，共 ${steps.length} 步：\n  ${names}\n` +
          "点击确定=授权在本机浏览器执行全部步骤（C1，整链一次）。");
        if (!ok) { log("已取消（C1 未授权）"); running = false; go.disabled = false; stop.disabled = true; return; }
      } else if (skillWrites && autoConfirm) {
        log("auto 模式：整链 C1 授权由调用方持有，跳过确认卡");
      }
      const resolved = resolveChainSteps(steps);
      const results: Array<{ step: number; status: string; runId?: number }> = [];
      for (let i = 0; i < resolved.length; i++) {
        if (stopRequested) { log(`已停止：第 ${i + 1} 步前中断`); break; }
        const st = resolved[i];
        const nm = `#${st.skill_id} ${steps[i].skill?.name ?? ""}`;
        log(`步骤 ${i + 1}/${resolved.length}：${nm} …`);
        try {
          const r = await runSkill(st.skill_id, st.overrides, log, () => stopRequested);
          results.push({ step: i + 1, status: r.status, runId: r.runId });
          log(`步骤 ${i + 1} 完成：${r.status}`);
          if (r.status !== "pass") {
            log(`链在第 ${i + 1} 步未通过——停止后续步骤（已执行 ${i + 1}/${resolved.length}）`);
            break;
          }
        } catch (e: any) {
          results.push({ step: i + 1, status: "error" });
          log(`步骤 ${i + 1} 失败：${e.message}——停止后续步骤`);
          break;
        }
      }
      const npass = results.filter((r) => r.status === "pass").length;
      const overall = npass === resolved.length && resolved.length > 0 ? "pass" : "fail";
      log(`链执行结束：${npass}/${resolved.length} 步通过（${overall}）`);
      showResultCard(overall, results.find((r) => r.runId)?.runId ?? null);
    } else {
      // ---- 单技能模式（原有路径） ----
      if (skillWrites && !autoConfirm) {
        const ok = confirm(
          `「${skillName}」含写操作。\n` +
          "点击确定=授权在本机浏览器执行全部步骤（C1）。");
        if (!ok) { log("已取消（C1 未授权）"); running = false; go.disabled = false; stop.disabled = true; return; }
      } else if (skillWrites && autoConfirm) {
        log("auto 模式：C1 授权由调用方持有，跳过确认卡");
      }
      // 换参注入：URL ?fill_<原值>=<新值> 映射进 overrides（回放写场景防
      // 唯一性冲突——JeecG 269 铁证：旧值已存在致 duplicate/check 拒绝，
      // addAll 永不发）
      const overrides: Record<string, string> = {};
      for (const [k, v] of params.entries()) {
        if (k.startsWith("fill_") && v) overrides[k.slice(5)] = v;
      }
      const r = await runSkill(skillId, overrides, log, () => stopRequested);
      log(`完成：${r.status}`);
      showResultCard(r.status, r.runId ?? null);
    }
  } catch (e: any) {
    log(`失败：${e.message}`);
    showResultCard("fail", null);
  }
  running = false;
  go.disabled = false;
  stop.disabled = true;
});

stop.addEventListener("click", () => {
  stopRequested = true;
  log("已请求停止——当前步骤完成后中断");
});
