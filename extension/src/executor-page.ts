// AG3 执行页：独立 tab 内跑步循环（popup 生命周期关不住、SW 消息层
// 不稳——十轮实证后终局架构：执行=专属页面，全程可见）
// UX 评审整改：确认卡带技能名+目标页；完成结果卡+工作台回看链接
// AH3/AR1 场景模式：?scenario=<id> 顺序执行多个技能（整场景 C1 一次确认、
// 步进报告、fail 即停）——场景=服务端纯数据，规则（${unique:}）在本页解释
export {};

import { listExecutorSkills, runSkill, setExecutorToken, api } from "./background/executor";
import { resolveRowAnchor, resolveStepOverrides } from "./shared/scenario-rules";

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

// AR1 场景模式数据：?scenario=<id>（与 ?skill= 互斥，场景优先）。
// 声明在 token 块之前（旧代码先引用后声明，TDZ 隐患顺手修）。
const scenarioId = Number(params.get("scenario") || 0);
let scenarioData: any = null;

if (tokenParam) {
  await setExecutorToken(tokenParam);
  const keep = scenarioId ? `?scenario=${scenarioId}` : (skillId ? `?skill=${skillId}` : "");
  history.replaceState(null, "", location.pathname + keep);
}

let skillName = `#${skillId}`;
let skillWrites = false;

if (scenarioId) {
  // 场景模式：拉场景数据（含技能概要）——标题/确认卡/步进报告都有据
  try {
    scenarioData = await api(`/scenarios/${scenarioId}`);
    const names = (scenarioData.steps || [])
      .map((st: any) => `#${st.skill_id} ${st.skill?.name ?? ""}`).join(" → ");
    title.textContent = `场景执行 ${scenarioData.name}`;
    meta.textContent = `${(scenarioData.steps || []).length} 个步骤：${names}`;
    skillWrites = (scenarioData.steps || []).some((st: any) => st.skill?.requires_confirmation);
    if (skillWrites) meta.textContent += "（含写操作——点击开始后需授权）";
  } catch (e: any) {
    log(`场景加载失败：${e.message}`);
    title.textContent = "场景执行（加载失败）";
  }
} else if (!skillId) {
  title.textContent = "SkillLens 执行器（未指定技能）";
  log("缺少 ?skill= 或 ?scenario= 参数——从 popup/空间选择进入。");
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
  if (running || (!skillId && !scenarioData)) return;
  running = true;
  stopRequested = false;
  go.disabled = true;
  stop.disabled = false;
  document.getElementById("result-card")!.style.display = "none";
  log("开始执行…");
  try {
    if (scenarioData) {
      // ---- AH3 场景执行：整场景 C1 一次确认 → 逐步执行 → fail 即停 ----
      const steps = scenarioData.steps || [];
      if (skillWrites && !autoConfirm) {
        const names = steps.map((st: any) =>
          `#${st.skill_id} ${st.skill?.name ?? ""}`).join("\n  ");
        const ok = confirm(
          `场景「${scenarioData.name}」含写操作，共 ${steps.length} 步：\n  ${names}\n` +
          "点击确定=授权在本机浏览器执行全部步骤（C1，整场景一次）。");
        if (!ok) { log("已取消（C1 未授权）"); running = false; go.disabled = false; stop.disabled = true; return; }
      } else if (skillWrites && autoConfirm) {
        log("auto 模式：整场景 C1 授权由调用方持有，跳过确认卡");
      }
      // AI2 逐步解析：每步执行时带前序产出 ctx（${stepN.字段} 跨步绑定），
      // unique 同轮共享时间戳。逐步而非整场景预解析——绑定值依赖执行期证据。
      const runTs = Date.now();
      const stepCtx: any[][] = [];
      const results: Array<{ step: number; status: string; runId?: number }> = [];
      for (let i = 0; i < steps.length; i++) {
        if (stopRequested) { log(`已停止：第 ${i + 1} 步前中断`); break; }
        // resolveStepOverrides 返回 overrides 字典本身（AI2 签名：step+ctx）
        const ovr = resolveStepOverrides(steps[i], stepCtx, runTs);
        // AN 跨步状态传递：row_anchor_from → 前序步 pickedRow 注入本步行锚
        // （选择类输出→输入；未命中保留原锚——resolveRowAnchor 纪律）
        const rowAnchor = steps[i].row_anchor_from
          ? (resolveRowAnchor(steps[i].row_anchor_from, stepCtx) ?? undefined)
          : undefined;
        if (steps[i].row_anchor_from && !rowAnchor) {
          log(`第 ${i + 1} 步行锚来源（步骤 ${steps[i].row_anchor_from}）无选择句柄——保留原锚`);
        }
        const nm = `#${steps[i].skill_id} ${steps[i].skill?.name ?? ""}`;
        log(`步骤 ${i + 1}/${steps.length}：${nm} …`);
        try {
          const r = await runSkill(steps[i].skill_id, ovr, log, () => stopRequested,
            undefined, rowAnchor);
          // 本步产出供后续步骤绑定（observed 写证据 + pickedRow 行键句柄）
          stepCtx.push([...(r.observed || []),
            ...(r.pickedRows || []).map((p: string) => ({ pickedRow: p }))]);
          results.push({ step: i + 1, status: r.status, runId: r.runId });
          log(`步骤 ${i + 1} 完成：${r.status}`);
          if (r.status !== "pass") {
            log(`场景在第 ${i + 1} 步未通过——停止后续步骤（已执行 ${i + 1}/${steps.length}）`);
            break;
          }
        } catch (e: any) {
          stepCtx.push([]);
          results.push({ step: i + 1, status: "error" });
          log(`步骤 ${i + 1} 失败：${e.message}——停止后续步骤`);
          break;
        }
      }
      const npass = results.filter((r) => r.status === "pass").length;
      const overall = npass === steps.length && steps.length > 0 ? "pass" : "fail";
      log(`场景执行结束：${npass}/${steps.length} 步通过（${overall}）`);
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
