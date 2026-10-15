// AG3 扩展执行器（协议客户端）：docs/arch/extension-executor-protocol.md
// 用户在 popup 选择技能并点击执行（含写技能——点击即 C1 授权）。
// SW 步循环：POST /executor/runs/{id}/step 交证据换指令；chrome.debugger
// 执行可信输入；先订阅 Network 后动作（lesson #30 时序）。
export {};

import { redactNetworkBody, redactNetworkUrl, redactValueAfter } from "../shared/redact";
import { AGENT_URL as AGENT } from "../shared/types";
import { resolveStepOverrides } from "../shared/scenario-rules";
import { Budget } from "../shared/budget";
import { describeFailure } from "../shared/failures";
import { isLoginUrl, writeEffectFired, writeResponseCount } from "../shared/expectations";

interface Instruction {
  seq: number;
  op: string;
  timeout_ms: number;
  url?: string;
  label?: string;
  name?: string;
  value?: string;
  phase?: string;
  scopes?: string[];
  resolve_candidates?: Array<{ strategy: string; selector: string; kind?: string }>;
}

let tokenCache = "";

export async function setExecutorToken(t: string): Promise<void> {
  tokenCache = t;
  await chrome.storage.local.set({ sl_executor_token: t });
}

export async function getToken(): Promise<string> {
  if (tokenCache) return tokenCache;
  const { sl_executor_token } = await chrome.storage.local.get("sl_executor_token");
  tokenCache = sl_executor_token || "";
  return tokenCache;
}

export async function api(path: string, init?: RequestInit): Promise<any> {
  const t = await getToken();
  // 超时保护用 Promise.race——SW+CDP 托管浏览器组合下 fetch 挂
  // AbortSignal 会整体挂死（AG3 实证：cursor 永不推进）
  const fetcher = fetch(`${AGENT}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${t}` },
  });
  const res = await Promise.race([
    fetcher,
    new Promise<never>((_, rej) =>
      setTimeout(() => rej(new Error("api timeout 30s")), 30000)),
  ]) as Response;
  if (!res.ok && res.status === 401) {
    throw new Error("未登录或会话过期（工作台登录后重试）");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function recoverLoginSession(debuggee: any, targetUrl: string): Promise<boolean> {
  /** AJ2 插件端恢复：目标 URL→系统名（服务端 /adapters/match 同源
   * 语义——这里用 url origin 匹配适配器 base_url）→POST 恢复端点→
   * cookie 经 CDP Network.setCookie 注入常驻浏览器。 */
  try {
    let system = "";
    try {
      const r = await api(`/adapters/match?url=${encodeURIComponent(targetUrl)}`);
      system = String((r || {}).system || (r || {}).id || "");
    } catch { /* match 失败——无适配器系统 */ }
    if (!system) return false;
    const res = await api("/executor/session/recover", {
      method: "POST",
      body: JSON.stringify({ system }),
    });
    const cookies = (res || {}).cookies || [];
    if (!(res || {}).recovered || !cookies.length) return false;
    for (const c of cookies) {
      await chrome.debugger.sendCommand(debuggee, "Network.setCookie", {
        name: c.name, value: c.value, domain: c.domain, path: c.path || "/",
        ...(typeof c.expires === "number" && c.expires > 0 ? { expires: c.expires } : {}),
      }).catch(() => {});
    }
    return true;
  } catch { return false; }
}

export async function listExecutorSkills(): Promise<any[]> {
  return api("/executor/skills");
}

// ---- 执行器主体 ----

export async function runSkill(
  skillId: number, overrides: Record<string, string>,
  onProgress: (msg: string) => void,
  shouldStop?: () => boolean,
  hostTab?: number,
  rowAnchor?: string,
): Promise<{ status: string; runId?: number; observed?: any[]; pickedRows?: string[] }> {
  const plan = await api(`/executor/skills/${skillId}/plan`, {
    method: "POST",
    body: JSON.stringify({ overrides, confirm_side_effect: true }),
  });
  const runId: number = plan.run_id;
  // P1 交互画像（平台化组件化）：系统交互差异的声明式载体——执行器
  // 特化行为改为画像解释（无画像走内置默认=通用行为）。
  // 入口统一重置全部跨运行全局（评审 #6：残留画像/搜索值/GetItems 标记
  // 会污染同页签下一个技能——错误吞噬 click/误触发重导航）
  (globalThis as any).__ip = plan.interaction_profile || null;
  (globalThis as any).__gotoTargetUrl = undefined;
  (globalThis as any).__getItemsDone = false;
  (globalThis as any).__lastSearchValue = "";
  onProgress(`已创建执行 #${runId}（${plan.total_instructions} 条指令）`);

  // 执行页签获取（AH6 页内执行）：hostTab 指定=直接在该页签执行（用户
  // 正在看的业务页——goto 步会把页面导航到技能入口，全程用户可见），
  // 收尾只 detach 不动页签。未指定=原逻辑（空白页复用/新建）。
  let tabId: number | undefined;
  // 复用的页签是用户自己开的——收尾只能导航回 about:blank，不能 remove
  let tabReused = false;
  if (hostTab != null) {
    tabId = hostTab;
    onProgress("在当前页面执行（本页将被驱动）");
  } else {
    try {
      const all = await chrome.tabs.query({});
      const blank = all.find((t) => !t.url || t.url === "about:blank");
      if (blank?.id) {
        tabId = blank.id;
        tabReused = true;
        onProgress("复用空白页签执行");
      } else {
        const created = await Promise.race([
          chrome.tabs.create({ url: "about:blank", active: true }),
          new Promise((res) => setTimeout(() => res(null), 4000)),
        ]) as any;
        tabId = created?.id;
      }
    } catch { tabId = undefined; }
    if (!tabId) {
      await api(`/executor/runs/${runId}/finish`, {
        method: "POST",
        body: JSON.stringify({
          status: "fail",
          summary: { error: "无法获取执行页签（tabs.create 不可用——请打开一个空白页签后重试）" },
        }),
      });
      return { status: "fail" };
    }
  }
    const debuggee = { tabId };
  try {
    await chrome.debugger.attach(debuggee, "1.3");
      } catch (e: any) {
    // AK6 批次1：attach 冲突按四码分类——fatal 不重试，白话直达
    // （620 run 风暴实证：此形态原样重试只会秒败秒建）
    const f = describeFailure(e);
    await api(`/executor/runs/${runId}/finish`, {
      method: "POST",
      body: JSON.stringify({ status: "fail", summary: { error: `attach 失败：${e.message}（关闭 DevTools 后重试）`, code: f.code, plain: f.plain } }),
    });
    await releaseExecTab(debuggee, tabId, tabReused, hostTab != null);
    return { status: "fail" };
  }
  onProgress("已 attach（顶部横幅=执行中，全程可见）");

  // AK2 run 级预算（120s 默认）：整技能硬封顶——治慢页挂死（单步 30s
  // 定位×N 步无界累计的根治）；步间检查剩余，耗尽走 terminate 强杀
  const runBudget = new Budget(120_000);

  // 网络证据：先订阅后动作（lesson #30）；AG4 补响应体（断言原料）。
  // 评审 #7/#8：listener 具名+finally 移除（多轮执行不再累积泄漏闭包）；
  // pendingBodies 请求结束即删（Map 无界增长根治）
  const networkLog: any[] = [];
  const pendingBodies = new Map<string, string>();
  // AI2：请求体暂存（requestWillBeSent 存，responseReceived 落 networkLog）
  const pendingReqBodies = new Map<string, string>();
  const onEvt = (source: any, method: string, params: any) => {
    if (source.tabId !== tabId) return;
    if (method === "Network.requestWillBeSent") {
      // AI2 跨步传值：请求体（postData）必须留——${stepN.字段} 绑定的提取
      // 原料。脱敏后存（红线：请求体含凭据形态——与 net-hook 同语义）
      pendingBodies.set(params?.requestId, params?.request?.method || "GET");
      pendingReqBodies.set(params?.requestId,
        redactNetworkBody(params?.request?.postData || ""));
      // 315 第七环（socid=59 铁证）：经典表单整页提交的 POST 是文档请求
      // ——导航销毁页面时 responseReceived 不再到达，写请求从不上
      // networkLog（AM1 误拦真提交）。写方法请求**发出即记**（水位判
      // 定语义=动作发生，非响应落地）。
      const m = (params?.request?.method || "GET").toUpperCase();
      if (m === "POST" || m === "PUT" || m === "PATCH") {
        // 体检🟡④：CDP 重定向对同 requestId 重发 requestWillBeSent——
        // 已入列不重复（否则水位虚高，AM1 可能把真拦截误判已写）
        if (!networkLog.some((n) => n.requestId === params?.requestId
                               && n.method === m)) {
          networkLog.push({
            url: redactNetworkUrl(params?.request?.url || ""),
            status: undefined, requestId: params?.requestId, method: m,
            reqBody: redactNetworkBody(params?.request?.postData || ""),
            body: "",
          });
        }
      }
      return;
    }
    if (method === "Network.loadingFinished" || method === "Network.loadingFailed") {
      // 方法名记入日志后即可删（响应体若已取，networkLog 持有快照）
      pendingBodies.delete(params?.requestId);
      pendingReqBodies.delete(params?.requestId);
      return;
    }
    if (method === "Network.responseReceived") {
      // 已在 requestWillBeSent 发出即记的写请求不重复入列（只补状态）
      const preIdx = networkLog.findIndex(
        (n) => n.requestId === params?.requestId && n.status === undefined);
      if (preIdx >= 0) {
        networkLog[preIdx].status = params?.response?.status;
        // 重录批（goto 实例段通用化）：文档型写请求的响应 URL 是重定向
        // 后的最终 URL（含新实体 id——/hardware/{id}）——更新供
        // ${stepN.res_id} 提取
        if (params?.response?.url) {
          networkLog[preIdx].url = redactNetworkUrl(params.response.url);
        }
        pendingBodies.delete(params?.requestId);
        pendingReqBodies.delete(params?.requestId);
        return;
      }
      const url: string = redactNetworkUrl(params?.response?.url || "");
      networkLog.push({
        url, status: params?.response?.status,
        requestId: params?.requestId,
        method: pendingBodies.get(params?.requestId) || "GET",
        // AI2 跨步传值：请求体随响应落日志（绑定提取原料）
        reqBody: pendingReqBodies.get(params?.requestId) || "",
        body: "",
      });
      // 响应体异步取（AG0 实证 Network.getResponseBody 可用；失败留空）
      const idx = networkLog.length - 1;
      chrome.debugger.sendCommand(debuggee, "Network.getResponseBody", {
        requestId: params?.requestId,
      }).then((b: any) => {
        // 安全红线：响应体经 redactNetworkBody（JSON 递归敏感键掩码
        // /urlencoded 脱敏）——与录制侧 net-hook.js 同源语义
        networkLog[idx].body = redactNetworkBody(b?.body || "");
      }).catch(() => { /* 已导航/流式体不可取——留空不阻塞 */ })
        .finally(() => {
          pendingBodies.delete(params?.requestId);
          pendingReqBodies.delete(params?.requestId);
        });
    }
  };
  chrome.debugger.onEvent.addListener(onEvt);
  await chrome.debugger.sendCommand(debuggee, "Network.enable").catch(() => {});

  const t0 = Date.now();
  let instruction: Instruction | null = plan.instruction;
  let steps = 0;
  let stepsSinceGoto = 0;
  let recentWriteMark = 0;  // AM1 预拉放行水位（上步末写响应计数）
  const stepPickedRows: string[] = [];  // AN 行键聚合（链模式跨步传递）
  let anchorInjected = false;  // AN row_anchor_from 单次注入标记
  const failedSteps: any[] = [];  // s44：未救回步记录（防假 pass）
  try {
    while (instruction && instruction.op !== "detach") {
      // 用户停止（当前步完成后中断——UX 评审 P2：真停）
      if (shouldStop?.()) {
        onProgress("用户停止——当前步后中断");
        await Promise.race([
          api(`/executor/runs/${runId}/finish`, {
            method: "POST",
            body: JSON.stringify({ status: "aborted",
              summary: { error: "用户停止", executed: [], observed: [] } }) }),
          new Promise((res) => setTimeout(res, 8000)),
        ]).catch(() => {});
        return { status: "aborted", runId };
      }
      // 导航失败（目标站不可达）即中止——不再执行后续步骤（错误页上
      // 的点击是假执行）
      if (instruction.op === "goto") {
        const probe = await chrome.debugger.sendCommand(debuggee,
          "Runtime.evaluate", {
            expression: "location.href.startsWith('chrome-error://')",
            returnByValue: true }).catch(() => null);
        if (probe?.result?.value === true) {
          onProgress("目标站不可达——中止执行");
          break;
        }
      }
      // after 快照执行后留晚到响应窗口（写后的异步拉取如 Odoo mail
      // thread 实证晚 1-2s——web_save 已过而 messages 晚到漏采）
      if (instruction.op === "snapshot" && instruction.phase === "after") {
        await sleep(2500);
      }
      // AN row_anchor_from 注入：链模式传入的行键直接替换本步 row-trigger
      // 候选的 anchor（选择类输出→输入——无需知道旧锚文本，141 铁证：
      // 「请选择列表项」=前序选择未传递）。注入时 row-trigger 候选**前置**
      // ——通用文本候选会命中任意行的同名链接（E2E 实证：Update 文本
      // 候选先中首行，带锚候选没机会跑）。注入只做一次（首个带行锚的 click）。
      if (rowAnchor && instruction.op === "click" && !anchorInjected) {
        const cands: any[] = instruction.resolve_candidates || [];
        const rt = cands.filter(c => c?.kind === "row-trigger" || c?.anchor);
        if (rt.length) {
          instruction.resolve_candidates = [
            ...rt, ...cands.filter(c => !rt.includes(c))];
          for (const cand of rt) cand.anchor = rowAnchor;
          anchorInjected = true;
          onProgress(`行锚注入：${rowAnchor.slice(0, 40)}（来自前序步选择）`);
        }
      }
      const ev = await execute(debuggee, tabId, instruction, networkLog,
        onProgress, stepsSinceGoto);
      stepsSinceGoto = instruction.op === "goto" ? 0 : stepsSinceGoto + 1;
      steps++;
      // AN：本步行键聚合（evidence.pickedRow 由 execute 落——链模式原料）
      if (ev?.evidence?.pickedRow) stepPickedRows.push(ev.evidence.pickedRow);
      // s44 假 pass 收口：未救回的 miss/unsupported 步记录（finish 据此
      // 如实判 fail——干预救回的步以 ok 重报不落此）
      // s45 收口：error 步（AM1 写水位快败=提交被拦截强证据）也计入——
      // 排除它会让服务端恢复性判定空转，断言恰好全过就翻 pass 假阳
      // （run 3210 实证）。服务端 only_miss 判据会正确区分 miss/error。
      if (ev.result !== "ok" && ev.result !== "duplicate") {
        failedSteps.push({ seq: ev.seq, result: ev.result,
                           label: instruction.label || instruction.name || instruction.op });
      }
      // AM1 写效果水位（期望-观测对比，docs/specs/2026-10-10-am-*.md）：
      // expect_write 指令（服务端编译期声明）执行后必须观测到写响应——
      // 无写=静默失败（提交被表单校验拦截），快败+白话直达。预拉放行：
      // 前一交互已触发写（框架去重）不算拦截（服务端 runner 同语义）。
      if (instruction.expect_write && ev.result === "ok") {
        const mark = writeResponseCount(networkLog);
        const prePull = mark > recentWriteMark;
        let sawWrite = prePull;
        // 体检🟡③：水位等待受 runBudget 约束——预算耗尽立即放弃等待
        // （走无写判定语义），不叠加固定 6s 超支
        for (let w = 0; w < 20 && !sawWrite && !runBudget.exhausted(); w++) {
          await sleep(300);
          if (writeEffectFired(networkLog, mark)) sawWrite = true;
        }
        if (!sawWrite) {
          onProgress(`click ${instruction.label} 后无写请求——提交被拦截`);
          ev.result = "error";
          ev.evidence = { ...ev.evidence, error:
            "点击后无写请求（提交被拦截）——表单校验未通过或前置状态缺失" };
        }
      }
      recentWriteMark = writeResponseCount(networkLog);
      // 导航失败即中止（错误页上的后续步骤是假执行——UX 评审致命 2）
      if (ev.result === "error") {
        // s45 收口：当前 error 步计入 failed_steps——否则服务端恢复性
        // 判定只看断言全过就翻 pass 假阳（run 3210/3241 双实证：
        // AM1 拦截步走此专用路径，绕过通用收集）
        failedSteps.push({ seq: ev.seq, result: "error",
                           label: instruction.label || instruction.name || instruction.op });
        await Promise.race([
          api(`/executor/runs/${runId}/step`, {
            method: "POST", body: JSON.stringify(ev) }),
          new Promise((res) => setTimeout(res, 8000)),
        ]).catch(() => {});
        await Promise.race([
          api(`/executor/runs/${runId}/finish`, {
            method: "POST",
            body: JSON.stringify({ status: "fail",
              // C3 红线：error 中止同样落全证据（315 实证：AM1 拦截步
              // 走此路径曾把 networkLog 整体丢弃——observed 归零无法归因）
              summary: { error: ev.evidence?.error || "导航失败",
                         failed_steps: failedSteps,
                         executed: [],
                         observed: networkLog.filter((n) => n.url && n.url.startsWith("http")) } }) }),
          new Promise((res) => setTimeout(res, 8000)),
        ]).catch(() => {});
        onProgress(`中止：${ev.evidence?.error || "导航失败"}`);
        return { status: "fail" };
      }
      // AG3：步 POST race——卡点浮出为错误而非静默挂死。45s 绝对上限
      // （服务端 miss 介入自愈可到 30s+，8s 假阳性实锤）；
      // AK2：run 预算先到先触发（整技能硬封顶——预算耗尽快败不挂死）
      const stepPost = api(`/executor/runs/${runId}/step`, {
        method: "POST",
        body: JSON.stringify(ev),
      });
      const resp = await Promise.race([
        stepPost,
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error(`step POST 挂起 seq=${ev.seq}`)), 45000)),
        new Promise<never>((_, rej) => {
          if (runBudget.exhausted()) rej(runBudget.timeoutError("run"));
        }),
      ]);
      instruction = resp.instruction;
    }
    await chrome.debugger.sendCommand(debuggee, "Page.enable").catch(() => {});
    const title = await pageTitle(debuggee);
    const finish = await api(`/executor/runs/${runId}/finish`, {
      method: "POST",
      body: JSON.stringify({
        // s44 假 pass 实证（run 2890）：步 miss 未救回但恒发 done →
        // 0 断言空真 pass。未救回的 miss/unsupported 步必须如实判 fail
        // （干预救回的步会以 ok 重报——不影响）
        status: failedSteps.length ? "fail" : "done",        summary: {
          failed_steps: failedSteps,
          executed: [], observed: networkLog.filter((n) => n.url && n.url.startsWith("http")),
          duration_ms: Date.now() - t0, page_title: title, steps,
        },
      }),
    });
    onProgress(`完成：${finish.status}（${steps} 步）`);
    // AI2 跨步传值：把写请求证据带回调用方（链模式的下一步绑定原料）。
    // 与 finish.summary.observed 同源（判定用同一份；凭据已脱敏）
    // AN：pickedRows（行触发命中的行键）随返回——${stepN.row}/row_anchor_from 原料
    const pickedRows = stepPickedRows;
    return { status: finish.status, runId,
             observed: networkLog.filter((n) => n.url && n.url.startsWith("http")),
             pickedRows: pickedRows.length ? pickedRows : undefined };
  } catch (e: any) {
    onProgress(`中断：${e.message}`);
    // AK2 超时/预算耗尽 → CDP 强杀页面内挂死例程（zcode L749-775 同款：
    // 防页面内 3s 例程外溢成整体挂死——terminate 立即中断 JS 执行）
    if (/预算耗尽|挂起 seq=|Timeout/i.test(String(e?.message || ""))) {
      await chrome.debugger.sendCommand(debuggee, "Runtime.terminateExecution")
        .catch(() => {});
    }
    // 诊断核心：错误必须落库（race 保护 finish 自身也不挂死）
    await Promise.race([
      api(`/executor/runs/${runId}/finish`, {
        method: "POST",
        body: JSON.stringify({
          status: "aborted",
          summary: { error: e.message, executed: [] },
        }),
      }).catch(() => {}),
      new Promise((res) => setTimeout(res, 8000)),
    ]);
    return { status: "aborted" };
  } finally {
    chrome.debugger.onEvent.removeListener(onEvt);
    await releaseExecTab(debuggee, tabId, tabReused, hostTab != null);
  }
}

// 收尾释放执行页签：自建页签直接关；复用的是用户自己开的空白页签，
// 只能导航回 about:blank（关掉会销毁用户的页签——评审三轮 🟡）。
async function releaseExecTab(debuggee: any, tabId: number, reused: boolean,
                              hostTab = false): Promise<void> {
  await chrome.debugger.detach(debuggee).catch(() => {});
  if (hostTab) return;  // AH6：页内执行——页面留在原地（用户继续用）
  if (!reused) {
    await chrome.tabs.remove(tabId).catch(() => {});
    return;
  }
  await chrome.tabs.update(tabId, { url: "about:blank" }).catch(() => {});
}

async function pageTitle(debuggee: any): Promise<string> {
  try {
    const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: "document.title", returnByValue: true,
    });
    return r?.result?.value || "";
  } catch { return ""; }
}

async function execute(
  debuggee: any, tabId: number, ins: Instruction,
  networkLog: any[], onProgress: (m: string) => void,
  stepsSinceGoto = 0,
): Promise<{ seq: number; result: string; evidence: any }> {
  const evidence: any = { network: [], toasts: [] };
  // AO1（引擎零系统知识）：菜单项选择器从画像读——默认=原硬编码值
  // （antd/element-plus），系统可在 adapters/*.yaml 的
  // interaction_profile.dropdown.menu_item_selector 覆盖
  const ipMenuSel = ((globalThis as any).__ip?.dropdown?.menu_item_selector)
    || '.ant-dropdown-menu-item, .el-dropdown-menu__item';
  if (ins.op === "goto") {
    // AH6 页内执行：目标≈当前 URL 则跳过导航——两次 Page.navigate 会
    // 销毁页面上下文（悬浮面板/用户输入状态全丢）；已在目标页是页内
    // 执行的常态（面板就在该系统页上发起）
    try {
      const cur = await chrome.debugger.sendCommand(debuggee,
        "Runtime.evaluate", { expression: "location.href", returnByValue: true });
      const curUrl = String(cur?.result?.value || "");
      const same = curUrl.split("#")[0].split("?")[0]
        === String(ins.url).split("#")[0].split("?")[0];
      if (same) {
        onProgress(`已在目标页（${curUrl.slice(0, 50)}）——跳过导航`);
        return { seq: ins.seq, result: "ok", evidence };
      }
    } catch { /* 探测失败走正常导航 */ }
    onProgress(`导航 ${ins.url}`);
    await chrome.debugger.sendCommand(debuggee, "Page.enable").catch(() => {});
    // hash 路由 SPA（Odoo 等）会从 localStorage 恢复视图状态（如 kanban
    // 无 New 按钮）——先访问 origin 根清状态再进目标 URL（服务端新
    // context 无此病史，插件端复用浏览器必须清）
    try {
      const origin = new URL(ins.url!).origin;
      await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: origin });
      await sleep(800);
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: "try { localStorage.clear(); } catch (e) {}" });
    } catch { /* fail-open */ }
    await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: ins.url });
    // SPA 渲染+hydration 余量（JeecG 实证：表格行渲染≠React 事件挂载
    // ——elClick ok 但 onClick 未绑模态不开；就绪信号后固定 2s 余量）
    for (let w = 0; w < 8; w++) {
      await sleep(500);
      try {
        const ready = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "!!(document.querySelector('.ant-table-row, tr, .ant-table-tbody') "
            + "&& document.querySelectorAll('.ant-table-row, tbody tr').length >= 0)",
          returnByValue: true });
        if (ready?.result?.value === true) break;
      } catch { /* fail-open */ }
    }
    await sleep(2000);
    // goto 目标 URL 记录（fill 前偏移自愈用——236 铁证的异步 set_route
    // 防护锚点）
    (globalThis as any).__gotoTargetUrl = ins.url;
    // 残留弹窗清理（若依 257 实证：上一技能的确认弹窗跨 tab 罩住后续
    // goto 页面——texts 只剩 返回首页/取消/确定，新增按钮全被遮）。
    // 可见 el-message-box/el-dialog 的确定/取消按钮逐个点掉（幂等）
    try {
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(async function(){
          for (let i = 0; i < 3; i++) {
            const boxes = [...document.querySelectorAll(
              '.el-message-box, .el-overlay:not([style*="display: none"])')]
              .filter(b => b.getBoundingClientRect().width > 0);
            if (!boxes.length) return i;
            const btn = [...boxes[0].querySelectorAll('button')]
              .find(b => /确\\s*定|Cancel|取消/.test((b.textContent||'').trim()));
            if (!btn) return i;
            btn.click();
            await new Promise(r => setTimeout(r, 600));
          }
          return 3;
        })()`, returnByValue: true, awaitPromise: true });
    } catch { /* fail-open */ }
    // 目标 URL 校验+重导航（ERPNext 236 铁证：Submit 后 SPA 自动跳转与
    // goto 竞态——确认时在目标页、fill 时被弹回旧页（quotation）——
    // 步执行全打到错误页面。校验 pathname 前缀不匹配则重导航一次）
    try {
      const targetPath = new URL(ins.url!).pathname.replace(/\/new-[^/]+$/, "/new-");
      for (let navTry = 0; navTry < 2; navTry++) {
        const u = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "location.href", returnByValue: true });
        const finalUrl = String(u?.result?.value || "");
        const curPath = new URL(finalUrl).pathname.replace(/\/new-[^/]+$/, "/new-")
          .replace(/^\/desk\//, "/app/");
        const tgtNorm = targetPath.replace(/^\/desk\//, "/app/");
        if (curPath === tgtNorm || finalUrl.startsWith("chrome-error://") || finalUrl === "about:blank") {
          onProgress(`导航后实际页面: ${finalUrl.slice(0, 60)}`);
          if (finalUrl.startsWith("chrome-error://") || finalUrl === "about:blank") {
            return { seq: ins.seq, result: "error",
                     evidence: { ...evidence, error: `目标站不可达: ${redactNetworkUrl(String(ins.url || ""))}` } };
          }
          break;
        }
        if (navTry === 0) {
          onProgress(`导航偏移（${curPath}≠${tgtNorm}）——重导航`);
          await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: ins.url });
          await sleep(3000);
        }
      }
      // SPA 晚到跳转防护（ERPNext 236 铁证：上一步 Submit 的异步
      // location 跳转在 goto 确认后数十秒才到达——把页面弹回旧页，
      // 后续步全打到错误页面。长守卫窗口：15s 内任何时刻偏移→重导航）
      let guardOk = false;
      for (let s = 0; s < 10; s++) {
        await sleep(1500);
        const u2 = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "location.pathname", returnByValue: true }).catch(() => null);
        const cur = String(u2?.result?.value || "");
        const seg = tgtNorm.split("/").filter(Boolean).slice(-2).join("/");
        if (!cur.includes(seg)) {
          onProgress(`守卫检测到页面偏移（${cur.slice(0, 40)}）——重导航`);
          await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: ins.url });
          await sleep(2500);
          guardOk = false;
          continue;
        }
        guardOk = true;
      }
      if (guardOk) {
        // 最终确认一遍（重导航后）
        const u3 = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "location.pathname", returnByValue: true }).catch(() => null);
        if (!String(u3?.result?.value || "").includes(
            tgtNorm.split("/").filter(Boolean).slice(-2).join("/"))) {
          await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: ins.url });
          await sleep(2500);
        }
      }
    } catch { /* fail-open */ }
    // AM2 登录守卫（期望-观测对比，设计 docs/specs/2026-10-10-am-*.md）：
    // goto 后落登录路径=登录态丢失（e1_env 环境故障非链漂移）——run 2817
    // 实证：JeecG 登录页上 click 误报 ok、fill 全 miss 烧完 120s 预算，
    // 归因不可读。快败+白话直达（词表与服务端 failure_class 同源）。
    try {
      const u = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate",
        { expression: "location.href", returnByValue: true });
      const finalUrl = String(u?.result?.value || "");
      const loginFormProbe = await chrome.debugger.sendCommand(debuggee,
        "Runtime.evaluate", { expression:
          "!!(document.querySelector('input[name=username], input[name=password], #account')"
          + " && document.querySelector('input[type=password]'))",
        returnByValue: true }).catch(() => null);
      const loginByForm = String(loginFormProbe?.result?.value || "") === "true";
      if ((isLoginUrl(finalUrl) || loginByForm) && !isLoginUrl(String(ins.url || ""))) {
        // AJ2 闭环（插件端恢复）：守卫触发→调服务端恢复端点（适配器
        // 登录例程，凭据不出服务端）→cookie 注入常驻浏览器→重导航
        // 重试一次。失败才如实快败（e1_env）。
        onProgress(`登录态丢失（跳到登录页）——尝试自动恢复`);
        const recovered = await recoverLoginSession(debuggee, ins.url || "");
        if (recovered) {
          onProgress("登录态已恢复（cookie 注入）——重试当前步");
          await chrome.debugger.sendCommand(debuggee, "Page.navigate",
            { url: ins.url }).catch(() => {});
          await sleep(4000);
          const u2 = await chrome.debugger.sendCommand(debuggee,
            "Runtime.evaluate",
            { expression: "location.href", returnByValue: true }).catch(() => null);
          const retryUrl = String(u2?.result?.value || "");
          if (!isLoginUrl(retryUrl)) {
            return { seq: ins.seq, result: "ok", evidence: { ...evidence,
              session_recovered: true } };
          }
        }
        return { seq: ins.seq, result: "error",
                 evidence: { ...evidence, error:
                   `登录态丢失：目标页跳转到登录页（${redactNetworkUrl(finalUrl.slice(0, 60))}）`
                   + (recovered ? "——恢复后仍跳登录页" : "——自动恢复失败")
                   + "（e1_env 环境故障）" } };
      }
    } catch { /* 探测失败 fail-open */ }
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "snapshot") {
    // 证据链对齐服务端（S33）：before/after 页面快照（采集端同 schema
    // 精简版——forms 带脱敏）+ 截图（base64，服务端落盘 artifacts）
    try {
      const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `JSON.stringify((function(){
          // 安全红线：与录制侧 snapshot.ts 同源三重防线——password 跳过 /
          // autocomplete=password 旁路跳过 / label 敏感词脱敏
          // 词表与 shared/redact.ts BASE_SENSITIVE_PATTERNS 逐字一致
          // （页内脚本无法 import，一致性由 shared/redact-parity.test.ts 断言）
          const SENS = /password|passwd|secret|token|authorization|cookie|api_key|apikey|private_key|credential|密码|口令|密钥|令牌|凭证|验证码/i;
          const forms = [...document.querySelectorAll('input, select, textarea')]
            .filter(e => e.getBoundingClientRect().width > 0)
            .filter(e => {
              const ac = (e.getAttribute('autocomplete') || '').toLowerCase();
              return e.type !== 'password' && !ac.includes('password');
            })
            .slice(0, 30).map(e => {
              const label = (((e.closest('.form-group, .ant-form-item, .cgf-item') || {})
                .querySelector ? e.closest('.form-group, .ant-form-item, .cgf-item')
                  .querySelector('label')?.textContent : '') || e.placeholder || e.name || '');
              return { label: String(label || '').trim().slice(0, 40),
                       value: SENS.test(String(label || ''))
                         ? '[REDACTED]'
                         : String(e.value || '').slice(0, 60) };
            });
          const toasts = [...document.querySelectorAll(
            '.toast, .toast-message, .ant-message-notice, .el-message, [role=alert]')]
            .filter(e => e.offsetParent !== null)
            .map(e => (e.textContent || '').trim().slice(0, 80))
            // 敏感 toast 整条丢弃（红线：宁可缺失也不落敏感线索）
            .filter(t => t && !SENS.test(t));
          return {url: location.href, title: document.title, forms, toasts};
        })())`, returnByValue: true });
      try {
        // 文档 URL 也是证据：?token= 明文会随快照上行入库并进 LLM 归因
        const page = JSON.parse(r?.result?.value || "{}");
        if (page && typeof page.url === "string") page.url = redactNetworkUrl(page.url);
        evidence.page = page;
      } catch { /* noop */ }
    } catch { /* fail-open */ }
    try {
      const shot = await chrome.debugger.sendCommand(debuggee, "Page.captureScreenshot",
        { format: "png" });
      // 超限整张丢弃而非截断：服务端按 .png 落盘，截断的 base64 解出的是
      // 非法 PNG（工作台碎图）。宁缺毋坏——快照文本证据才是断言原料。
      const b64 = String(shot?.data || "");
      if (b64 && b64.length <= 300000) evidence.screenshot = b64;
    } catch { /* fail-open */ }
    onProgress(`快照（${ins.phase}）`);
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "click" || ins.op === "fill") {
    const label = ins.label || ins.name || "";
    // Get Items API 直调后的 UI 步吞噬（ERPNext 236：API 导入完成后，
    // 录制的后续 UI 步 [click on][click Get Items] 无意义——直接 ok）
    if (ins.op === "click" && (globalThis as any).__getItemsDone) {
      await sleep(300);
      onProgress(`click ${label}（Get Items API 已完成——跳过 UI 步）`);
      return { seq: ins.seq, result: "ok", evidence };
    }
    // 搜索结果行最优先（ERPNext 236 铁证：Get Items 弹窗 search_term 填后
    // 下一步「click on」的目标=结果列表里含搜索值的行——录制的 label 'on'
    // 是无意义残留；含 __lastSearchValue 的行命中才有效）
    const lastSearch = (globalThis as any).__lastSearchValue as string | undefined;
    if (ins.op === "click" && lastSearch) {
      const rowHit = await chrome.debugger.sendCommand(debuggee,
        "Runtime.evaluate", {
          expression: `(() => {
            const sv = ${JSON.stringify(lastSearch)};
            const modal = document.querySelector('.modal-content, [role=dialog]');
            if (!modal || modal.getBoundingClientRect().width === 0) return '';
            const rows = [...modal.querySelectorAll('li, .list-item, .select-item, .result-row, [class*=result]')]
              .filter(e => e.getBoundingClientRect().width > 0
                && (e.textContent||'').includes(sv));
            if (!rows.length) return '';
            const r = rows[0].getBoundingClientRect();
            return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
          })()`, returnByValue: true }).catch(() => null);
      let rowPos: {x: number, y: number} | null = null;
      try { rowPos = JSON.parse(rowHit?.result?.value || "") || null; } catch { /* null */ }
      if (rowPos) {
        (globalThis as any).__lastSearchValue = "";
        await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
          type: "mouseMoved", x: rowPos.x, y: rowPos.y });
        await sleep(300);
        await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
          type: "mousePressed", x: rowPos.x, y: rowPos.y, button: "left", clickCount: 1 });
        await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
          type: "mouseReleased", x: rowPos.x, y: rowPos.y, button: "left", clickCount: 1 });
        await sleep(1200);
        onProgress(`click ${label}（搜索结果行）`);
        return { seq: ins.seq, result: "ok", evidence };
      }
    }
    // 开着的 dropdown 菜单项最优先（JeecG 270 铁证：seq3 开菜单后 seq4
    // 的目标就是菜单项——resolver/探针查 button 全空转，菜单保持开着
    // 点击落空。菜单项是 li 非 button，React onClick 走 mousedown 委托
    // 必须 trusted 坐标点击。P1：匹配模式/挂载窗口由画像 dropdown 驱动）
    const ipDD = (globalThis as any).__ip?.dropdown;
    const ddMatch = ipDD?.menu_item_match || "includes";
    const ddWaitMs = ipDD?.mount_wait_ms || 400;
    if (ins.op === "click") {
      for (let ddWait = 0; ddWait < 3; ddWait++) {
        const ddItem = await chrome.debugger.sendCommand(debuggee,
          "Runtime.evaluate", {
            expression: `(() => {
              const label = ${JSON.stringify(label)};
              const match = (t) => ${JSON.stringify(ddMatch)} === 'exact'
                ? t === label : t.includes(label);
              const items = [...document.querySelectorAll(
                ${JSON.stringify(ipMenuSel)})]
                .filter(e => e.getBoundingClientRect().width > 0
                  && match((e.textContent||'').trim()));
              if (!items.length) return '';
              const r = items[0].getBoundingClientRect();
              return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
            })()`, returnByValue: true }).catch(() => null);
        let ddPos: {x: number, y: number} | null = null;
        try { ddPos = JSON.parse(ddItem?.result?.value || "") || null; } catch { /* null */ }
        if (ddPos) {
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mouseMoved", x: ddPos.x, y: ddPos.y });
          await sleep(300);
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mousePressed", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mouseReleased", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
          await sleep(1200);
          onProgress(`click ${label}（菜单项）`);
          return { seq: ins.seq, result: "ok", evidence };
        }
        await sleep(ddWaitMs);
      }
    }
    // fill 直通 JS 设值（官方 harness 本质：data-fieldname/placeholder/
    // form-item label 三级查找+input 事件派发——ERPNext 234 PASS 实证；
    // resolver 候选对 fill 的 form-group 命中错元素/多元素 miss 实证）
    if (ins.op === "fill" && ins.value !== undefined) {
      // Odoo m2o 关系字段适配（链 22 实证）：placeholder 含
      // "Type to find"（Odoo 特征）——fill 只设值不触发选中协议，
      // Confirm 被表单校验拦。正确链=输入→等下拉→点第一项
      try {
        const m2o = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(async function(){
            const label = ${JSON.stringify(label)};
            const inp = [...document.querySelectorAll('input')].find(
              i => (i.placeholder || '').includes('Type to find'));
            if (!inp) return '';
            const set = Object.getOwnPropertyDescriptor(
              HTMLInputElement.prototype, 'value').set;
            set.call(inp, ${JSON.stringify(String(ins.value))});
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            await new Promise(r => setTimeout(r, 1500));
            const item = [...document.querySelectorAll(
              '.o-autocomplete--dropdown-item, .ui-menu-item, [role=option]')]
              .find(o => o.getBoundingClientRect().width > 0
                && (o.textContent || '').trim().length > 0
                && !/create|search more/i.test(o.textContent || ''));
            if (item) {
              item.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
              item.click();
              await new Promise(r => setTimeout(r, 1000));
              return 'ok:' + inp.value.slice(0, 20);
            }
            return '';
          })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
        const m2ov = String(m2o?.result?.value || "");
        if (m2ov.startsWith("ok:")) {
          await sleep(500);
          onProgress(`fill ${label}（Odoo m2o 下拉选中）`);
          return { seq: ins.seq, result: "ok",
                   evidence: { network: [], toasts: [],
                               value_after: redactValueAfter(label, m2ov.slice(3)) } };
        }
      } catch { /* 非 Odoo 页——走通用链 */ }
            // select2 型目标适配（Snipe/Livewire 系统实证）：原生 select 被
      // select2 接管（AJAX 懒加载选项）——JS 设值无效且选项未加载。
      // 正确链=select2 open→轮询选项→mouseup+click（select2 4.x 监听
      // mouseup，单纯 click 不选中——LWOK1 真机三字段终验实证）
      try {
        const s2 = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(async function(){
            const label = ${JSON.stringify(label)};
            const sel = document.querySelector('select[name="' + label + '"]');
            if (!sel || !window.jQuery) return '';
            if (!sel.parentElement || !sel.parentElement.querySelector('.select2-container')) return '';
            const target = ${JSON.stringify(String(ins.value))};
            for (let round = 0; round < 3; round++) {
              // 前置 click 步可能已开下拉（触发器点击态不定）——先关再开
              // 消除状态叠加（executor 链特有：click Select X → fill x_id）
              try { jQuery(sel).select2('close'); } catch (e) { /* 未开 */ }
              try { jQuery(sel).select2('open'); } catch (e) { return ''; }
              for (let i = 0; i < 10; i++) {
                await new Promise(r => setTimeout(r, 400));
                const opt = [...document.querySelectorAll('.select2-results__option')]
                  .find(o => o.textContent && o.textContent.includes(target)
                    && o.getAttribute('aria-disabled') !== 'true');
                if (opt) {
                  opt.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                  opt.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                  await new Promise(r => setTimeout(r, 400));
                  // select2 选中不走原生事件链——补 change 通知
                  // Livewire wire:model（LWFIN2 实证：无此行 Save 提交空表单）
                  sel.dispatchEvent(new Event('change', {bubbles: true}));
                  await new Promise(r => setTimeout(r, 600));
                  if (sel.value) return 'ok:' + sel.value;
                }
              }
            }
            return '';
          })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
        const s2v = String(s2?.result?.value || "");
        if (s2v.startsWith("ok:")) {
          await sleep(400);
          onProgress(`fill ${label}（select2 选项选中）`);
          return { seq: ins.seq, result: "ok",
                   evidence: { network: [], toasts: [],
                               value_after: redactValueAfter(label, s2v.slice(3)) } };
        }
      } catch { /* 非 select2 页——走通用 fill 链 */ }
      // 直通+重试（模态/抽屉渲染窗口——JeecG 新增点击后模态 1-2s 才开，
      // 首次查找空实证）
      let setVal: any = null;
      let lastFillDebug = "";
      for (let tryN = 0; tryN < 5; tryN++) {
        // 页面偏移自愈（ERPNext 236 铁证：Get Items From 点击触发的
        // 异步 set_route 在 fill 时刻把页面弹到源单列表——fill 全 miss）。
        // **有弹窗时不重导航**（弹窗随整页导航销毁——重导航后 fill 的
        // 目标 input 不在了；Frappe 的 set_route 会自己回到目标页
        // ——urltrace 实证 +89s 偏移 +95s 自愈回）。仅无弹窗且持续
        // 偏离（第 3 轮起）才重导航
        try {
          const gUrl = (globalThis as any).__gotoTargetUrl as string | undefined;
          if (gUrl && tryN >= 2) {
            const uc = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
              expression: `location.pathname + '|' + !!document.querySelector(
                '.modal-content, [role=dialog], .ant-modal-content')`,
              returnByValue: true }).catch(() => null);
            const parts = String(uc?.result?.value || "").split("|");
            const curP = parts[0] || "";
            const hasModal = parts[1] === "true";
            const tgtSeg = new URL(gUrl).pathname.split("/").filter(Boolean).slice(-2).join("/");
            if (tgtSeg && !hasModal && !curP.includes(tgtSeg.split("/").pop() || "##")) {
              onProgress(`fill 前页面偏移（${curP.slice(0, 36)}）——重导航`);
              await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: gUrl });
              await sleep(3000);
            }
          }
        } catch { /* fail-open */ }
        setVal = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(async function(){
            const label = ${JSON.stringify(label)};
            // Frappe Link 字段优先走 cur_frm.set_value（Frappe 官方
            // harness 同源：Link 字段的 customer 联动只有 set_value 触发
            // 服务端解析——JS 设 input.value 不进 Link 事件链，保存时
            // Customer 空 Missing Fields——ERPNext 235 铁证）
            try {
              if (window.cur_frm && cur_frm.doc
                  && cur_frm.fields_dict[label]
                  && ['Link', 'Dynamic Link'].includes((cur_frm.fields_dict[label].df || {}).fieldtype)) {
                await cur_frm.set_value(label, ${JSON.stringify(String(ins.value))});
                return (cur_frm.doc[label] || '') + '|frm';
              }
            } catch (e) { /* 非 Frappe 页面——走通用链 */ }
            // Frappe Table 子字段（Item Code 等）：录制的 UI 搜索选择流在
            // 自动执行中点击落空——走 frappe.model.set_value 行通道（235
            // 铁证：item_code 设后 item_name/uom 服务端自动带全）
            try {
              if (window.cur_frm && cur_frm.doc && label === 'Item Code') {
                const items = cur_frm.doc.items || [];
                const first = items[0];
                if (first) {
                  await frappe.model.set_value(first.doctype, first.name,
                    'item_code', ${JSON.stringify(String(ins.value))});
                  await new Promise(r => setTimeout(r, 1500));
                  const it = (cur_frm.doc.items || [])[0] || {};
                  return (it.item_code || '') + '|row';
                }
              }
            } catch (e) { /* 非 Frappe——通用链 */ }
            let target = null;
            // ① name 精确匹配最优先（Snipe 303 铁证：label=asset_tags[1]
            // 是 name 形态——placeholder/form-group 链全 miss，值从未
            // 写进表单，Save 恒空表单被拦）
            const byName = [...document.querySelectorAll(
              'input[name="' + label + '"], textarea[name="' + label + '"]')]
              .filter(e => e.getBoundingClientRect().width > 0);
            if (byName.length === 1) target = byName[0];
            else if (byName.length > 1) {
              const inModal = byName.find(e => e.closest(
                '.modal-content, .ant-modal-content, [role=dialog]'));
              target = inModal || byName[0];
            }
            // data-fieldname 多处同名（ERPNext 236 铁证：列表视图搜索栏与
            // Get Items 弹窗都有 search_term——querySelector 取文档序第一
            // 个=列表栏，modal 内的漏掉；modal/对话框内优先）
            const dfAll = [...document.querySelectorAll('[data-fieldname="' + label + '"] input')]
              .filter(e => e.getBoundingClientRect().width > 0);
            const dfInModal = dfAll.find(e => e.closest(
              '.modal-content, .modal-dialog, [role=dialog], .ant-modal-content'));
            const df = dfInModal || dfAll[0] || null;
            if (df) target = df;
            if (!target) {
              const phs = [...document.querySelectorAll('input')]
                .filter(e => e.placeholder === label
                  && e.getBoundingClientRect().width > 0);
              if (phs.length === 1) target = phs[0];
              else if (phs.length > 1) {
                const inModal = phs.find(e => e.closest(
                  '.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]'));
                target = inModal || phs[0];
              }
            }
            if (!target) {
              // ③ form-item label 匹配。同 label 双处命中时 modal/抽屉内
              // 优先（真机铁证：modal 开着时列表页查询栏同 label form-item
              // 文档序在前——值写进搜索框，保存必 miss）
              const bare = label.replace(/[*\\s]/g, '');
              const groups = [...document.querySelectorAll(
                '.ant-form-item, .cgf-item, .form-group')];
              const hits = [];
              for (const g of groups) {
                const lbl = (g.querySelector('label')?.textContent || '')
                  .replace(/[*\\s]/g, '');
                if (lbl === bare) {
                  const inp = g.querySelector('input');
                  if (inp && inp.getBoundingClientRect().width > 0) hits.push(inp);
                }
              }
              const inModal = hits.find(e => e.closest(
                '.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]'));
              target = inModal || hits[0] || null;
            }
            if (!target) {
              // ④ 原生 name/id 匹配（禅道 zentao 表单 input[name=title]——
              // 无 data-fieldname/placeholder/form-item 标记的裸表单）
              const byName = document.querySelector(
                'input[name="' + label + '"], textarea[name="' + label + '"], #' + label);
              if (byName && byName.getBoundingClientRect().width > 0) target = byName;
            }
            if (!target) return 'MISS|df=' + (df ? 'hidden' : 'none') + '|url=' + location.pathname.slice(0, 40) + '|n=' + document.querySelectorAll('[data-fieldname]').length;
            // ZCode harness 模式：focus+execCommand insertText（真实输入，
            // isTrusted 事件框架全兼容）；失败回退 native setter。
            // focus 后验证 activeElement（ZCode inputTargetToken 同语义
            // ——模态 autofocus 抢夺时 insertText 会打到错误元素）
            target.focus();
            if (document.activeElement !== target) return '';
            target.select?.();
            const okCmd = document.execCommand('insertText', false,
              ${JSON.stringify(String(ins.value))});
            if (!okCmd) {
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(target, ${JSON.stringify(String(ins.value))});
              target.dispatchEvent(new Event('input', {bubbles: true}));
              target.dispatchEvent(new Event('change', {bubbles: true}));
            }
            return target.value;
          })()`, returnByValue: true, awaitPromise: true });
        const v = setVal?.result?.value;
        if (v && !String(v).startsWith("MISS")) { lastFillDebug = String(v).slice(0, 60); break; }
        if (v) lastFillDebug = String(v).slice(0, 60);
        if (setVal?.exceptionDetails) {
          lastFillDebug = 'EXC:' + String(setVal.exceptionDetails.exception?.description || setVal.exceptionDetails.text || '').slice(0, 80);
        }
        await sleep(2000);
      }
      const val0 = String(setVal?.result?.value || "");
      const val = val0.startsWith("MISS") ? "" : val0;
      // Get Items From 直调（ERPNext 236 终局）：fill search_term 的目标是
      // 把 quotation items 导入 SO——不等 fill UI 成功（页面跳变下必 miss），
      // 直接按指令 value 走 make_sales_order API；成功则后续 UI 步吞噬
      if (ins.op === "fill" && /search/i.test(label)
          && String(ins.value || "").startsWith("SAL-")) {
        const mapped = await chrome.debugger.sendCommand(debuggee,
          "Runtime.evaluate", {
            expression: `(async () => {
              try {
                if (!window.cur_frm || cur_frm.doctype !== 'Sales Order') return 'wrong-form:' + (cur_frm ? cur_frm.doctype : 'none');
                const body = new URLSearchParams({source_name: ${JSON.stringify(String(ins.value))}});
                const csrf = (window.frappe && frappe.csrf_token) || '';
                const resp = await fetch('/api/method/erpnext.selling.doctype.quotation.quotation.make_sales_order', {
                  method: 'POST', body, credentials: 'include',
                  headers: {'X-Frappe-CSRF-Token': csrf,
                            'X-Requested-With': 'XMLHttpRequest'}});
                const data = await resp.json();
                const doc = data.message;
                if (!doc || !doc.items) return 'no-items';
                for (const row of doc.items) {
                  const child = cur_frm.add_child('items');
                  Object.assign(child, row);
                }
                cur_frm.refresh_field('items');
                return 'imported=' + cur_frm.doc.items.length;
              } catch (e) {
                return 'ERR ' + String(e).slice(0, 80);
              }
            })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
        const mv = String(mapped?.result?.value || "");
        if (mv.startsWith("imported")) {
          (globalThis as any).__getItemsDone = true;
          await sleep(800);
          onProgress(`fill ${label}（Get Items API 直调 ${mv}）`);
          return { seq: ins.seq, result: "ok",
                   evidence: { network: [], toasts: [], value_after: redactValueAfter(String(ins.label || ins.name || ""), ins.value) } };
        }
        onProgress(`Get Items API 未成（${mv.slice(0, 40)}）——fill UI 路径`);
      }
      if (val) {
        await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "(document.activeElement || {}).blur && document.activeElement.blur()" })
          .catch(() => {});
        // 搜索型 fill（Get Items From 弹窗 search_term——ERPNext 236 铁证）：
        // fill 直通成功即触发 make_sales_order API 导入（UI 搜索/选择在
        // 异步 set_route 跳变下不收敛——HTTP form-encoded 200 实证），
        // 后续 [click on][Get Items] UI 步被 __getItemsDone 吞噬
        if (/search/i.test(label) && val && !String(val).startsWith("MISS")) {
          (globalThis as any).__lastSearchValue = val;
          const mapped = await chrome.debugger.sendCommand(debuggee,
            "Runtime.evaluate", {
              expression: `(async () => {
                try {
                  if (!window.cur_frm || cur_frm.doctype !== 'Sales Order') return 'wrong-form';
                  const body = new URLSearchParams({source_name: ${JSON.stringify(String(val))}});
                  const resp = await fetch('/api/method/erpnext.selling.doctype.quotation.quotation.make_sales_order', {
                    method: 'POST', body, credentials: 'include'});
                  const data = await resp.json();
                  const doc = data.message;
                  if (!doc || !doc.items) return 'no-items';
                  for (const row of doc.items) {
                    const child = cur_frm.add_child('items');
                    Object.assign(child, row);
                  }
                  cur_frm.refresh_field('items');
                  return 'imported=' + cur_frm.doc.items.length;
                } catch (e) {
                  return 'ERR ' + String(e).slice(0, 80);
                }
              })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
          const mv = String(mapped?.result?.value || "");
          if (mv.startsWith("imported")) {
            (globalThis as any).__getItemsDone = true;
            (globalThis as any).__lastSearchValue = "";
            await sleep(800);
            onProgress(`fill ${label}（Get Items API 直调 ${mv}）`);
            return { seq: ins.seq, result: "ok",
                     evidence: { network: [], toasts: [], value_after: redactValueAfter(String(ins.label || ins.name || ""), val) } };
          }
          onProgress(`Get Items API 未成（${mv.slice(0, 36)}）——UI 路径`);
        }
        (globalThis as any).__lastSearchValue = /search/i.test(label) ? val : "";
        await sleep(2500);
        onProgress(`fill ${label}（JS 设值）`);
        return { seq: ins.seq, result: "ok", evidence: { network: [], toasts: [], value_after: redactValueAfter(String(ins.label || ins.name || ""), val) } };
      }
      // 主 frame 三级+name 查找全空——iframe 表单兜底（禅道 272 铁证：
      // story/create 表单在外壳页的内嵌 iframe——zcode domSnapshot 同样
      // 递归 iframe；走 CDP frame context 求值）
      try {
        const tree = await chrome.debugger.sendCommand(debuggee, "Page.getFrameTree");
        const frames: any[] = [];
        (function walk(n: any) {
          if (n?.frame) frames.push(n.frame);
          (n?.childFrames || []).forEach(walk);
        })(tree?.frameTree);
        for (const f of frames) {
          if (!f.parentId) continue;
          try {
            const world = await chrome.debugger.sendCommand(debuggee,
              "Page.createIsolatedWorld",
              { frameId: f.id, grantUniversalAccess: true });
            const cid = world?.executionContextId;
            if (!cid) continue;
            const fv = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
              contextId: cid, returnByValue: true,
              expression: `(function(){
                const label = ${JSON.stringify(label)};
                let t = document.querySelector('input[name="' + label + '"], textarea[name="' + label + '"], #' + label);
                if (!t) {
                  const phs = [...document.querySelectorAll('input')]
                    .filter(e => e.placeholder === label
                      && e.getBoundingClientRect().width > 0);
                  t = phs[0] || null;
                }
                if (!t || t.getBoundingClientRect().width === 0) return '';
                t.focus();
                t.select?.();
                const ok = document.execCommand('insertText', false,
                  ${JSON.stringify(String(ins.value))});
                if (!ok) {
                  const set = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                  set.call(t, ${JSON.stringify(String(ins.value))});
                  t.dispatchEvent(new Event('input', {bubbles: true}));
                  t.dispatchEvent(new Event('change', {bubbles: true}));
                }
                return t.value;
              })()` });
            const v = fv?.result?.value;
            if (v) {
              await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
                contextId: cid,
                expression: "(document.activeElement || {}).blur && document.activeElement.blur()" })
                .catch(() => {});
              await sleep(300);
              onProgress(`fill ${label}（iframe 内设值）`);
              return { seq: ins.seq, result: "ok",
                       evidence: { network: [], toasts: [], value_after: redactValueAfter(String(ins.label || ins.name || ""), v) } };
            }
          } catch { /* 此 frame 不可入——继续下一个 */ }
        }
      } catch { /* getFrameTree 失败 fail-open */ }
      // JS 设值未命中——落回 resolver 路径（重试+介入）。诊断随行
      onProgress(`fill ${label} 直通miss ${lastFillDebug || 'empty'}——resolver 兜底`);
    }
    // 模态提交分支前置（270 铁证：「开始同步」在同步确认 modal 里——
    // resolver 对 modal footer 按钮必 miss，miss return 后模态分支永远
    // 执行不到）。P1：按钮正则/选择器/取位由交互画像 modal_submit 驱动
    // （无画像走默认）
    const ipMS = (globalThis as any).__ip?.modal_submit;
    const msRegex = ipMS?.button_regex || "保存|确定|提\\s*交|同步";
    const msSelector = ipMS?.selector || ".ant-modal-content, .ant-drawer-content";
    const msPick = ipMS?.pick || "last_visible";
    if (ins.op === "click" && new RegExp(msRegex).test(label)) {
      let modalBtn: any = null;
      for (let w = 0; w < 4 && modalBtn?.result?.value !== "ok"; w++) {
        modalBtn = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(function(){
            const modal = document.querySelector(${JSON.stringify(msSelector)});
            if (!modal || modal.getBoundingClientRect().width === 0) return '';
            const re = new RegExp(${JSON.stringify(msRegex)});
            const btns = [...modal.querySelectorAll('button')]
              .filter(e => re.test((e.textContent||'').trim())
                && e.getBoundingClientRect().width > 0);
            if (btns.length) {
              (${JSON.stringify(msPick)} === 'first_visible' ? btns[0] : btns[btns.length - 1]).click();
              return 'ok';
            }
            return '';
          })()`, returnByValue: true }).catch(() => null);
        if (modalBtn?.result?.value !== "ok") await sleep(800);
      }
      if (modalBtn?.result?.value === "ok") {
        await sleep(2000);
        onProgress(`click ${label}（模态提交）`);
        return { seq: ins.seq, result: "ok", evidence };
      }
    }
    // 对齐 locate 语义：异步渲染重试。zcode 纪律（3s 短预算快失败+错误即
    // 导航）：miss 快速上报让服务端介入/豁免接住——重试轮次里绝不 reload
    // （reload 会摧毁已开的 modal——JeecG #269 铁证：seq3 开 modal 后 seq4
    // 聚焦步 miss 轮 reload 把 modal 摧毁，fill 无处可写死循环）。reload
    // 只保留给 goto 首指令后的首个定位（SPA 视图状态病重载即愈，且此时
    // 无已开 modal 可摧毁）
    const firstLocateAfterGoto = stepsSinceGoto === 0;
    const maxAttempts = firstLocateAfterGoto ? 8 : 3;
    let resolved: any = null;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      resolved = await resolve(debuggee, ins, label, onProgress);
      if (resolved?.hit) break;
      if (attempt === 3 && firstLocateAfterGoto) {
        try {
          await chrome.debugger.sendCommand(debuggee, "Page.reload");
          await sleep(2500);
        } catch { /* fail-open */ }
        continue;
      }
      await sleep(1000);
    }
    if (!resolved?.hit) {
      onProgress(`定位失败：${label}（触发服务端介入）`);
      // 协议 §4：miss 附页面可见文本（服务端 LLM 提案的输入）
      let texts: string[] = [];
      try {
        const t = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `JSON.stringify([...document.querySelectorAll(
            'button, a, [role="button"], input, label, .form-group, .ant-form-item')]
            .map(e => (e.textContent || '').trim()).filter(t => t && t.length < 40).slice(0, 80))`,
          returnByValue: true,
        });
        texts = JSON.parse(t?.result?.value || "[]");
      } catch { /* fail-open */ }
      return { seq: ins.seq, result: "miss",
               evidence: { ...evidence, miss: label, page_texts: texts } };
    }
    // AN 跨步状态传递：行触发命中时把 pickedRow（行键）落进证据——
    // runSkill 步循环聚合返回，链模式 ${stepN.row}/row_anchor_from 的原料
    if (resolved.pickedRow) evidence.pickedRow = resolved.pickedRow;
    // 通用滚入：行操作触发器常在视口右缘外（AG5 铁证 rect.x=1409>视口
    // 1280——坐标点击落空）。不限 row-trigger——role 命中的行内「更多」
    // 同病（270 铁证：rect 未滚 x=1438 落空，滚后 dropdown 才开）。
    // scrollIntoView 后重取 rect（cx 1439→1212 实证）
    try {
      const anchorJson = JSON.stringify(resolved.anchorTxt || "");
      const req = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const label = ${JSON.stringify(ins.label || ins.name || "")};
          const anchor = ${anchorJson};
          let el = null;
          if (anchor) {
            const rows = [...document.querySelectorAll('.ant-table-row, .list-item, .grid-row, tr')]
              .filter(r => (r.textContent || '').toLowerCase().includes(anchor.toLowerCase()));
            for (const row of rows) {
              const t = [...row.querySelectorAll('a, span, button')]
                .find(e => (e.textContent||'').trim() === label
                  && e.getBoundingClientRect().width > 0);
              if (t) { el = t; break; }
            }
          }
          if (!el) {
            el = [...document.querySelectorAll('span, a, button')]
              .filter(e => (e.textContent||'').trim() === label
                && e.getBoundingClientRect().width > 0)[0];
          }
          if (!el) return '';
          (el.closest('td, .ant-table-cell') || el)
            .scrollIntoView({block: 'center', inline: 'center'});
          return 'ok';
        })()`, returnByValue: true });
      if (req?.result?.value === "ok") {
        await sleep(400);
        const rr = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(function(){
            const label = ${JSON.stringify(ins.label || ins.name || "")};
            const anchor = ${JSON.stringify(resolved.anchorTxt || "")};
            let el = null;
            if (anchor) {
              const rows = [...document.querySelectorAll('.ant-table-row, .list-item, .grid-row, tr')]
                .filter(r => (r.textContent || '').toLowerCase().includes(anchor.toLowerCase()));
              for (const row of rows) {
                const t = [...row.querySelectorAll('a, span, button')]
                  .find(e => (e.textContent||'').trim() === label
                    && e.getBoundingClientRect().width > 0);
                if (t) { el = t; break; }
              }
            }
            if (!el) {
              el = [...document.querySelectorAll('span, a, button')]
                .filter(e => (e.textContent||'').trim() === label
                  && e.getBoundingClientRect().width > 0)[0];
            }
            if (!el) return '';
            const r = el.getBoundingClientRect();
            return JSON.stringify({x: r.x, y: r.y, width: r.width, height: r.height});
          })()`, returnByValue: true });
        try {
          const nr = JSON.parse(rr?.result?.value || "");
          if (nr && nr.width) resolved.rect = nr;
        } catch { /* 用原 rect */ }
      }
    } catch { /* fail-open */ }
    // label 元素命中：坐标点击不触发关联控件（label 无 for 时不转发）
    // ——元素级 click() 走 label 原生转发（服务端 locate 同语义）
    // iframe 内按钮（frame 命中）：坐标系换算不可靠（CDP frame context
    // 坐标与主视口差值非 iframe rect——禅道实证 432 vs 480）——原生
    // form submit 按钮用元素级 click()（HTML 表单提交不校验 isTrusted）
    if (resolved.fromFrame && resolved.tagName === "button"
        && ins.op === "click") {
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const btns = [...document.querySelectorAll('button')]
            .filter(e => (e.textContent||'').trim() === ${JSON.stringify(label)}
              && e.getBoundingClientRect().width > 0);
          if (btns.length === 1) { btns[0].click(); return 'ok'; }
          return '';
        })()`, contextId: resolved.frameContextId });
      await sleep(1500);
      onProgress(`${ins.op} ${label}（frame 元素级）`);
      return { seq: ins.seq, result: "ok", evidence };
    }
    // 保存/确定/提交/同步类点击+模态开着：模态 footer primary 优先（JeecG 实证
    // 保存步 ok 但 addAll 未发——点中列表页同名按钮；官方 harness 模式
    // =模态上下文的提交按钮）。真机铁证：JeecG cgform modal footer 有
    // 多个同名"保存"（各配置 tab 的隐藏 footer 都在 DOM）——必须过滤
    // 可见（rect>0）且取**最后一个**（页面级 footer 在 DOM 尾部）；
    // 「开始同步」在同步确认 modal footer（270 铁证）
    if (resolved.tagName === "label") {
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const labels = [...document.querySelectorAll('label')]
            .filter(e => (e.textContent||'').trim() === ${JSON.stringify(label)}
              && e.getBoundingClientRect().width > 0);
          if (labels.length === 1) { labels[0].click(); return 'ok'; }
          return '';
        })()` });
      await sleep(1000);
      onProgress(`${ins.op} ${label}（label 转发）`);
      return { seq: ins.seq, result: "ok", evidence };
    }
    const rect = resolved.rect;
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    // zcode actionProbe 模式（browserPlaywrightLocatorExecutor 一手源码）：
    // ①探针（visible+稳定双帧+hit-target）不 actionable 不点——JeecG 实证
    // 直点 4/5（hydration 窗口假 ok）探针 5/5 全开；②探针过先 elClick
    // （modal 类按钮 React onClick 明确；trusted 坐标流在 ant mask 上有
    // mousePressed 开 modal 后 mouseReleased 落 mask 触发关闭的时序风险
    // ——run943 实证 trusted 开了 modal 又被吞）③效果验证失败→trusted
    // 坐标点击兜底（双通道互补）④仍未开如实 miss（服务端介入）
    const probeAndClick = async (): Promise<{ clicked: boolean; reason?: string }> => {
      const ALIGN = ["center", "end", "start", "nearest"];
      for (let attempt = 0; attempt < 8; attempt++) {
        const probe = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(async () => {
            const label = ${JSON.stringify(label)};
            // span 类触发器也算（若依 258 铁证：.user-nickname 是 span——
            // hover dropdown 的触发器常非 button）
            // Dolibarr icon 链接族（新订单等）：title 属性承载人读标签
            // （textContent 空）——title 参与匹配（与录制侧 describeElement
            // 的 title 采集对齐）
            let els = [...document.querySelectorAll(
              'button, [role=button], .user-nickname, .el-dropdown > *, span, input[type=submit], input[type=button], a[title]')]
              .filter(e => ((e.textContent || e.value || e.title || '') + '').trim() === label
                && e.isConnected);
            // 可见过滤后再判唯一（ERPNext 铁证：页面有隐藏模板副本+真按钮
            // =2 命中直接 miss——隐藏者不参与唯一性竞争）
            const vis = els.filter(e => e.getBoundingClientRect().width > 0);
            if (vis.length >= 1) els = vis;
            // span 多命中常态（表格单元 span 同文本）——若命中者在
            // el-dropdown 容器内（hover 触发器语义），取**最内层叶子**
            // （若依 258 铁证：avatar-wrapper 容器与 nickname span 同文本
            // 同在 dropdown——容器嵌套 span，取无命中子孙的嵌套最深者）
            const inDd = els.filter(e => e.closest('.el-dropdown, .ant-dropdown'));
            if (inDd.length > 1) {
              const leaves = inDd.filter(e =>
                !inDd.some(x => x !== e && e.contains(x)));
              if (leaves.length >= 1) els = leaves;
            } else if (inDd.length === 1) {
              els = inDd;
            }
            if (els.length !== 1) return {count: els.length, actionable: false};
            const el = els[0];
            const st = getComputedStyle(el);
            if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0')
              return {count: 1, actionable: false, reason: 'hidden'};
            el.scrollIntoView({block: ${JSON.stringify(ALIGN[attempt % 4])},
              inline: 'center', behavior: 'instant'});
            const waitRaf = () => new Promise(res =>
              requestAnimationFrame(() => res()));
            let r = el.getBoundingClientRect(), stable = 0;
            for (let i = 0; i < 10 && stable < 2; i++) {
              await waitRaf();
              const cur = el.isConnected ? el.getBoundingClientRect() : null;
              if (!cur) return {count: 0, actionable: false};
              const same = r.left===cur.left && r.top===cur.top
                && r.width===cur.width && r.height===cur.height;
              stable = same ? stable + 1 : 0;
              r = cur;
            }
            if (stable < 2) return {count: 1, actionable: false, reason: 'not-stable'};
            const cx = r.left + r.width/2, cy = r.top + r.height/2;
            if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight)
              return {count: 1, actionable: false, reason: 'outside-viewport'};
            const hit = document.elementsFromPoint(cx, cy);
            if (!(hit.includes(el) || (hit[0] && el.contains(hit[0]))))
              return {count: 1, actionable: false, reason: 'covered'};
            return {count: 1, actionable: true, x: cx, y: cy};
          })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
        const p = probe?.result?.value;
        if (p?.actionable) {
          // 行内 ant-dropdown 触发器前置检测（JeecG 270 铁证：行内「更多」
          // button 在表格行内且页面有同名多行——elClick 开不了 ant-dropdown
          // 菜单，且**elClick+trusted 连点会 toggle 抵消**（JS click 先翻转
          // React 状态，trusted 再点=关）。命中行内元素时直接 trusted 点击）
          const isRowDropdownTrigger = await chrome.debugger.sendCommand(debuggee,
            "Runtime.evaluate", {
              expression: `(() => {
                const label = ${JSON.stringify(label)};
                const els = [...document.querySelectorAll('button, [role=button]')]
                  .filter(e => (e.textContent||'').trim() === label
                    && e.getBoundingClientRect().width > 0
                    // 315 第七环：提交按钮（input submit）永远不是 dropdown
                    // 触发器——Dolibarr 等老式 table 布局表单在 tr 内的保存
                    // 按钮曾被误判走 trusted 点击（不触发原生 submit）
                    && e.tagName !== 'INPUT');
                if (els.length < 1) return false;
                return els.some(e => !!e.closest('.ant-table-row, .list-item, .grid-row, tr'));
              })()`, returnByValue: true }).catch(() => null);
          if (isRowDropdownTrigger?.result?.value === true) {
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mouseMoved", x: p.x, y: p.y });
            await sleep(400);
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mousePressed", x: p.x, y: p.y, button: "left", clickCount: 1 });
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mouseReleased", x: p.x, y: p.y, button: "left", clickCount: 1 });
            await sleep(900);
            return { clicked: true };
          }
          // hover-dropdown 触发器检测：命中元素在 el-dropdown 容器内
          // （trigger:"hover"）——elClick 无效（JS click 不触发 hover 菜单，
          // 若依 258 铁证），必须 trusted mouseMoved 停留等菜单挂载
          const isHoverTrigger = await chrome.debugger.sendCommand(debuggee,
            "Runtime.evaluate", {
              expression: `(() => {
                const label = ${JSON.stringify(label)};
                let els = [...document.querySelectorAll(
                  '.user-nickname, .el-dropdown > *, span')]
                  .filter(e => (e.textContent||'').trim() === label && e.isConnected);
                const vis = els.filter(e => e.getBoundingClientRect().width > 0);
                const inDd = vis.filter(e => e.closest('.el-dropdown, .ant-dropdown'));
                return inDd.length >= 1;
              })()`, returnByValue: true }).catch(() => null);
          if (isHoverTrigger?.result?.value === true) {
            // trusted hover 停留（菜单挂载窗口）
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mouseMoved", x: p.x, y: p.y });
            await sleep(1200);
            return { clicked: true };
          }
          // elClick 首选（React onClick 直触发，无坐标事件流的 mask 副作用）
          // **ant-dropdown 菜单项例外**（JeecG 270 铁证：菜单项 li 的 JS click
          // 不触发 onClick（React 事件委托在 li 的 mousedown），必须 trusted
          // 坐标——elClick 点后 dropdown 不关、modal 不开）
          const ddItem = await chrome.debugger.sendCommand(debuggee,
            "Runtime.evaluate", {
              expression: `(() => {
                const label = ${JSON.stringify(label)};
                const items = [...document.querySelectorAll(
                  ${JSON.stringify(ipMenuSel)})]
                  .filter(e => (e.textContent||'').trim() === label
                    && e.getBoundingClientRect().width > 0);
                if (!items.length) return '';
                const r = items[0].getBoundingClientRect();
                return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
              })()`, returnByValue: true }).catch(() => null);
          let ddPos: {x: number, y: number} | null = null;
          try { ddPos = JSON.parse(ddItem?.result?.value || "") || null; } catch { /* null */ }
          if (ddPos) {
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mouseMoved", x: ddPos.x, y: ddPos.y });
            await sleep(300);
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mousePressed", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
            await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
              type: "mouseReleased", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
            await sleep(1000);
            return { clicked: true };
          }
          const el = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
            expression: `(async () => {
              const label = ${JSON.stringify(label)};
              let els = [...document.querySelectorAll(
                'button, [role=button], input[type=submit], input[type=button]')]
                .filter(e => ((e.textContent || e.value || '') + '').trim() === label && e.isConnected);
              const vis = els.filter(e => e.getBoundingClientRect().width > 0);
              if (vis.length >= 1) els = vis;
              if (els.length !== 1) return '';
              els[0].click();
              return 'ok';
            })()`, returnByValue: true, awaitPromise: true }).catch(() => null);
          if (el?.result?.value === "ok") {
            // ant-dropdown 触发器检测（JeecG 270 铁证：行内「更多」button
            // elClick 后 ant-dropdown 菜单**不展开**（需 trusted 事件）——
            // elClick 后验证菜单挂载，未挂载则改 trusted 坐标点击）
            await sleep(900);
            const ddOpen = await chrome.debugger.sendCommand(debuggee,
              "Runtime.evaluate", {
                expression: `(() => {
                  const items = [...document.querySelectorAll(
                    ${JSON.stringify(ipMenuSel)})]
                    .filter(e => e.getBoundingClientRect().width > 0);
                  return items.length;
                })()`, returnByValue: true }).catch(() => null);
            const menuCount = Number(ddOpen?.result?.value || 0);
            const inDropdownHost = await chrome.debugger.sendCommand(debuggee,
              "Runtime.evaluate", {
                expression: `(() => {
                  const label = ${JSON.stringify(label)};
                  return [...document.querySelectorAll(
                    '.ant-table-row, .ant-dropdown, .el-dropdown')]
                    .some(host => (host.textContent||'').includes(label));
                })()`, returnByValue: true }).catch(() => null);
            if (menuCount === 0 && inDropdownHost?.result?.value === true) {
              // trusted 坐标点击同元素（开 ant-dropdown 菜单）
              await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
                type: "mouseMoved", x: p.x, y: p.y });
              await sleep(300);
              await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
                type: "mousePressed", x: p.x, y: p.y, button: "left", clickCount: 1 });
              await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
                type: "mouseReleased", x: p.x, y: p.y, button: "left", clickCount: 1 });
              await sleep(900);
            }
            return { clicked: true };
          }
          // trusted 坐标兜底（elClick 未命中时）——**hover 流入版**：
          // 先 mouseMoved 到触发器（hover dropdown 的开闸信号）等菜单
          // 挂载，无菜单再普通三事件点击（若依 trigger:"hover" 铁证：
          // 单 click 不开 hover 菜单，必须 hover 停留）
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mouseMoved", x: p.x, y: p.y });
          await sleep(1000);
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mousePressed", x: p.x, y: p.y, button: "left", clickCount: 1 });
          await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
            type: "mouseReleased", x: p.x, y: p.y, button: "left", clickCount: 1 });
          return { clicked: true };
        }
        await sleep(250);
      }
      return { clicked: false, reason: "probe-budget" };
    };
    if (ins.op === "click") {
      const pc = await probeAndClick();
      if (pc.clicked) {
        await sleep(1200);
        // 效果验证（zcode setChecked 读回模式）：点击前无 modal、label 是
        // 新增/新建类时点击后应有 modal——无则 elClick 双通道重试（真机
        // 实证：trusted 坐标点击在 JeecG 偶发落空[run943]，elClick 同钮
        // 必开——两通道互补；重试仍无 modal 才如实 miss）
        // s44 实证（Dolibarr「创建合作方」input[submit]）：expect_write 步
        // 是提交按钮（整页跳转无 modal）——expectModal 必须排除，否则
        // 点击成功却因无 modal 误判 miss
        const expectModal = !ins.expect_write
          && /新增|新建|添加|创建|New|Create|Add/i.test(label)
          && !/取消|关闭/.test(label);
        if (expectModal) {
          const modalOpen = async (): Promise<boolean> => {
            const m = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
              expression: `!!(document.querySelector(
                '.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]')
                && document.querySelector('.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]').getBoundingClientRect().width > 0)`,
              returnByValue: true }).catch(() => null);
            return !!m?.result?.value;
          };
          if (!(await modalOpen())) {
            const retry = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
              expression: `(function(){
                const els = [...document.querySelectorAll('button, [role=button]')]
                  .filter(e => (e.textContent||'').trim() === ${JSON.stringify(label)}
                    && e.getBoundingClientRect().width > 0);
                if (els.length === 1) { els[0].click(); return 'ok'; }
                return '';
              })()`, returnByValue: true });
            if (retry?.result?.value === "ok") {
              await sleep(1500);
              if (await modalOpen()) {
                onProgress(`click ${label}（重试通道兜住）`);
                return { seq: ins.seq, result: "ok", evidence };
              }
            }
            onProgress(`click ${label}（双通道后 modal 仍未开——miss）`);
            return { seq: ins.seq, result: "miss", evidence };
          }
        }
        onProgress(`click ${label}（探针+trusted）`);
        return { seq: ins.seq, result: "ok", evidence };
      }
      // 探针预算尽：回退旧元素级（label 转发等场景）
      const elClick = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const els = [...document.querySelectorAll('button, [role=button]')]
            .filter(e => (e.textContent||'').trim() === ${JSON.stringify(label)}
              && e.getBoundingClientRect().width > 0);
          if (els.length === 1) { els[0].click(); return 'ok'; }
          return '';
        })()`, returnByValue: true });
      if (elClick?.result?.value === "ok") {
        await sleep(1200);
        onProgress(`click ${label}（元素级兜底）`);
        return { seq: ins.seq, result: "ok", evidence };
      }
    }
    // hover 先行：mouseenter 态组件先展开；随后正常 click（服务端
    // row-trigger 即 JS click——ant-dropdown 的 onClick 含 open 逻辑，
    // hover-only 假设被服务端 pass 行为证伪）。
    // dropdown 流入点击（若依 258 铁证）：hover 触发的 el-dropdown（trigger:
    // "hover"）在菜单出现后**鼠标须连续流入菜单项**——移出即关。步骤：
    // hover 触发器→等待菜单项出现（rect>0）→沿直线 move 到菜单项→click。
    // 菜单项查询覆盖 el-dropdown-menu__item/li 精确文本匹配
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseMoved", x, y });
    await sleep(1000);
    // AO1：hover 流入场景的宽兜底链从画像读（含 li——比 menu_item_selector
    // 更宽，是 dropdown 匹配失败后的最后防线）
    const ipMenuFallback = ((globalThis as any).__ip?.dropdown
      ?.menu_item_selector_fallback)
      || '.el-dropdown-menu__item, .ant-dropdown-menu-item, li [role=menuitem], li';
    const ddItem = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: `(function(){
        const items = [...document.querySelectorAll(
          ${JSON.stringify(ipMenuFallback)})]
          .filter(e => (e.textContent||'').trim() === ${JSON.stringify(label)}
            && e.getBoundingClientRect().width > 0);
        if (!items.length) return '';
        const r = items[0].getBoundingClientRect();
        return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2});
      })()`, returnByValue: true }).catch(() => null);
    let ddPos: {x: number, y: number} | null = null;
    try { ddPos = JSON.parse(ddItem?.result?.value || "") || null; } catch { /* 无菜单 */ }
    if (ddPos) {
      // 连续流入（中途移出=菜单关）
      await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
        type: "mouseMoved", x: ddPos.x, y: ddPos.y });
      await sleep(400);
      await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
        type: "mousePressed", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
      await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
        type: "mouseReleased", x: ddPos.x, y: ddPos.y, button: "left", clickCount: 1 });
      await sleep(1200);
      // 确认弹窗（el-message-box 的确定按钮——退出类操作的二段确认）
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const btns = [...document.querySelectorAll(
            '.el-message-box button, .el-message-box__btns button')];
          const btn = btns.find(x => (x.textContent||'').includes('确'));
          if (btn) { btn.click(); return 'ok'; }
          return '';
        })()`, returnByValue: true }).catch(() => {});
      await sleep(800);
      onProgress(`click ${label}（dropdown 流入）`);
      if (ins.op === "click") {
        return { seq: ins.seq, result: "ok", evidence };
      }
    }
    await sleep(0);
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseReleased", x, y, button: "left", clickCount: 1 });
    if (ins.op === "fill" && ins.value !== undefined) {
      // 官方 harness 本质（Frappe cypress fill_field→type→input 事件）：
      // JS 设值+dispatch input/change 事件——比模拟键击可靠（框架监听
      // 事件而非键击；ERPNext 实证 insertText+keyEvent 均未写入）
      const setVal = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const label = ${JSON.stringify(ins.label || ins.name || "")};
          // 目标：data-fieldname 容器内 input（Frappe）或 placeholder 匹配
          let target = null;
          const dfAll = [...document.querySelectorAll('[data-fieldname="' + label + '"] input')]
            .filter(e => e.getBoundingClientRect().width > 0);
          const dfInModal = dfAll.find(e => e.closest(
            '.modal-content, .modal-dialog, [role=dialog], .ant-modal-content'));
          const df = dfInModal || dfAll[0] || null;
          if (df) target = df;
          if (!target) {
            const phs = [...document.querySelectorAll('input')]
              .filter(e => e.placeholder === label
                && e.getBoundingClientRect().width > 0);
            if (phs.length === 1) target = phs[0];
            else if (phs.length > 1) {
              // 模态内优先（JeecG 两义性实证）
              const inModal = phs.find(e => e.closest(
                '.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]'));
              target = inModal || phs[0];
            }
          }
          if (!target) {
            // ant form-item label 匹配（JeecG "*表名"——label 去星号后
            // 与 form-item label 文本匹配，取组内 input）。同 label 双处
            // 命中时 modal/抽屉内优先（真机铁证：modal 开着时列表页查询
            // 栏同 label form-item 文档序在前——value 写进搜索框假 ok，
            // 保存必 miss）
            const bare = label.replace(/[*\\s]/g, '');
            const groups = [...document.querySelectorAll(
              '.ant-form-item, .cgf-item, .form-group')];
            const hits = [];
            for (const g of groups) {
              const lbl = (g.querySelector('label')?.textContent || '')
                .replace(/[*\\s]/g, '');
              if (lbl === bare) {
                const inp = g.querySelector('input');
                if (inp && inp.getBoundingClientRect().width > 0) hits.push(inp);
              }
            }
            const inModal = hits.find(e => e.closest(
              '.ant-modal-content, .ant-drawer-content, .el-dialog, [role=dialog]'));
            target = inModal || hits[0] || null;
          }
          if (!target) {
            // ④ 原生 name/id 匹配（禅道 zentao 表单 input[name=title]——
            // 无 data-fieldname/placeholder/form-item 标记的裸表单）
            const byName = document.querySelector(
              'input[name="' + label + '"], textarea[name="' + label + '"], #' + label);
            if (byName && byName.getBoundingClientRect().width > 0) target = byName;
          }
          if (!target) return '';
          // ZCode harness 模式（browserVirtualClipboard 一手源码）：
          // focus + execCommand("insertText")——浏览器原生命令产生
          // isTrusted input 事件，框架全兼容（React/Vue/Frappe）；
          // 失败时回退 native setter+dispatchEvent（快速路径）
          target.focus();
          target.select?.();
          const okCmd = document.execCommand('insertText', false,
            ${JSON.stringify(String(ins.value))});
          if (!okCmd) {
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value').set;
            setter.call(target, ${JSON.stringify(String(ins.value))});
            target.dispatchEvent(new Event('input', {bubbles: true}));
            target.dispatchEvent(new Event('change', {bubbles: true}));
          }
          return target.value;
        })()`, returnByValue: true });
      evidence.value_after = redactValueAfter(label, setVal?.result?.value || "");
      // blur：Odoo 等框架的 onchange/save 触发链需要输入框失焦（官方
      // tour 实证同模式）；下一个动作前统一 blur
      await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: "(document.activeElement || {}).blur && document.activeElement.blur()" })
        .catch(() => {});
      await sleep(300);
    }
    onProgress(`${ins.op} ${label}${resolved.strategy ? `（${resolved.strategy}）` : ""}`);
    return { seq: ins.seq, result: "ok", evidence };
  }
  // 未知指令：如实上报，服务端决定
  return { seq: ins.seq, result: "unsupported", evidence };
}

async function resolve(debuggee: any, ins: Instruction, label: string,
                       onDebug?: (m: string) => void,
                       isMainFrame = true): Promise<any> {
  const cands = ins.resolve_candidates || [];
  // CDP returnByValue 对对象返回对象（JSON.parse 炸）——js 末尾显式
  // stringify 保字符串契约（AG5 铁证：每轮 main err .slice undefined）
  // 主 frame 跳过 label 策略（禅道外壳 label 与 iframe 内真按钮同名——
  // 主 frame label 命中会点错对象；label 只在子 frame 兜底）
  const js = `JSON.stringify((function() {
    let rowAnchor = "";
    const skipLabel = /*SKIP_LABEL*/${isMainFrame ? "true" : "false"}/**/;
    const candidates = ${JSON.stringify(cands)}
      .filter(c => !skipLabel || c.strategy !== 'label');
    const label = ${JSON.stringify(label)};
    const visible = (el) => { if (!el.isConnected) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0; };
    // input[type=submit] 无 textContent——其 value 是人读标签（Dolibarr
    // 「创建合作方」铁证）；icon 链接（a[title]）title 承载标签（「新订单」
    // 铁证）——三者并集参与匹配
    const txt = (el) => ((el.textContent || el.value || el.title || '') + '').trim();
    // JeecG 必填星号形态（269 铁证：录制 label=「*表名」、页面渲染
    // 「表名」无星）——星号归一兜底：精确不中后按去星号比对
    const bare = (t) => String(t || '').replace(/[\s*]/g, '');
    for (const c of candidates) {
      let els = [];
      try {
        if (c.kind === "role") {
          let all = [...document.querySelectorAll(
            '[role="button"], button, input[type=submit], input[type=button]')]
            .filter(el => visible(el) && txt(el) === label);
          if (!all.length && /[\s*]/.test(label)) {
            all = [...document.querySelectorAll(
              '[role="button"], button, input[type=submit], input[type=button]')]
              .filter(el => visible(el) && bare(txt(el)) === bare(label));
          }
          // 多命中时模态/抽屉内优先（JeecG 保存步实证：列表页工具栏
          // 与模态 footer 同名"保存"——first 取到列表页错按钮）
          const inModal = all.filter(el => el.closest(
            '.ant-modal-content, .ant-drawer-content, .el-dialog, .modal, [role=dialog]'));
          els = inModal.length ? inModal : all;
        } else if (c.kind === "frappe-save") {
          // Frappe 官方 cypress save：button[data-label=Save]/.primary-action
          // （data-label 属性非文本——文本匹配 miss 实证）
          els = [...document.querySelectorAll(c.selector)].filter(visible);
        } else if (c.kind === "placeholder-modal") {
          // placeholder 两义性（JeecG "请输入表名"同页两处实证）：
          // 模态/抽屉容器内的 input 按 placeholder 过滤
          els = [...document.querySelectorAll(c.selector)]
            .filter(el => visible(el) && el.placeholder === label);
        } else if (c.kind === "form-group-control") {
          for (const g of document.querySelectorAll(c.selector)) {
            if (!(g.textContent||'').includes(label)) continue;
            const ctl = g.querySelector('.select2-container, .picker, .ant-select, .ant-picker');
            if (ctl && visible(ctl)) { els = [ctl]; break; }
          }
        } else if (c.kind === "form-group-native") {
          for (const g of document.querySelectorAll(c.selector)) {
            if (!(g.textContent||'').includes(label)) continue;
            const ctl = g.querySelector('input, select, textarea');
            if (ctl && visible(ctl)) { els = [ctl]; break; }
          }
        } else if (c.kind === "menuitem-text") {
          els = [...document.querySelectorAll(c.selector)]
            .filter(el => visible(el) && (el.textContent || "").trim() === label);
        } else if (c.kind === "row-trigger") {
          // AG5 行锚：含 anchor 词的行内找 label 文本触发器
          // AN 跨步状态传递：命中时捕获行首格文本（pickedRow——跨重渲
          // 稳定的行键，下一步 row_anchor_from 注入的原料）
          const rows = [...document.querySelectorAll(c.selector)]
            .filter(r => (r.textContent || "").toLowerCase().includes((c.anchor || "").toLowerCase()));
          for (const row of rows) {
            const trig = [...row.querySelectorAll(
              "a, span, button, [role=button], input[type=submit], input[type=button]")]
              .filter(el => visible(el) && txt(el) === label);
            if (trig.length) {
              els = [trig[0]]; rowAnchor = c.anchor || "";
              break;
            }
          }
        } else if (c.strategy === "text" && (c.selector || "").startsWith("//")) {
          // text 类候选是 XPath（normalize-space 精确匹配）——
          // querySelectorAll 不支持会静默空（Odoo 行内 <a>S00001</a> 实证：
          // 唯一命中通道）。等价语义：全可见元素精确文本匹配，优先可
          // 交互元素（a/button）再泛元素
          const exact = (el) => txt(el) === label;
          const interact = [...document.querySelectorAll(
            "a, button, [role=button], input[type=submit], input[type=button]")]
            .filter(el => visible(el) && exact(el));
          if (!interact.length) {
            // title-only 链接兜底（icon 链接族——Dolibarr「新订单」）
            const titled = [...document.querySelectorAll("a[title]")]
              .filter(el => visible(el) && (el.title || '').trim() === label);
            if (titled.length) { els = [titled[0]]; }
          }
          if (interact.length) { els = [interact[0]]; }
          else {
            const any = [...document.querySelectorAll("a, button, span, td, div")]
              .filter(el => visible(el) && exact(el)
                && ![...el.children].some(ch => exact(ch)));
            if (any.length) els = [any[0]];
          }
        } else {
          els = [...document.querySelectorAll(c.selector)].filter(visible);
        }
      } catch (e) { continue; }
      // role 精确匹配放宽：多个同名可见按钮时取第一个（ERPNext Save
      // 实证 texts 有 Save 但唯一性判定 miss——主按钮通常文档序最前）。
      // 行锚存在时优先锚行内的命中（JeecG 270 铁证：9 行各有「更多」
      // button——放宽取第一行=错行，dropdown 开在别的表上，同步链全断）
      if (els.length === 1 || (els.length > 1 && c.kind === "role")) {
        let pick = els[0];
        if (els.length > 1 && rowAnchor) {
          const inRow = els.filter(e => {
            const row = e.closest('.ant-table-row, .list-item, .grid-row, tr');
            return row && (row.textContent || "").toLowerCase()
              .includes(rowAnchor.toLowerCase());
          });
          if (inRow.length >= 1) pick = inRow[0];
        }
        const r = pick.getBoundingClientRect();
        // AN 跨步状态传递：命中元素在表格行内 → 捕获行键（首个非空格，
        // ≤80 字符）。不限 row-trigger 候选——唯一 label 点击走早期候选
        // 同样产出句柄（E2E 实证：tag 链接点击走文本候选，row-trigger
        // 未跑导致 pickedRow 落空）
        let prTxt = "";
        const prow = pick.closest(
          '.ant-table-row, .list-item, .grid-row, tr, [role=row]');
        if (prow) {
          for (const cell of prow.querySelectorAll("td, th")) {
            const t = (cell.textContent || "").trim();
            if (t) { prTxt = t.slice(0, 80); break; }
          }
          if (!prTxt) prTxt = (prow.textContent || "").trim().slice(0, 80);
        }
        return {hit: true, strategy: c.strategy, tagCls: (pick.className || ""),
          tagName: (pick.tagName || "").toLowerCase(),
          anchorTxt: rowAnchor || "",
          pickedRow: prTxt,
          rect: {x: r.x, y: r.y, width: r.width, height: r.height}};
      }
    }
    return {hit: false};
  })())`;
  // 多 frame resolve（对齐 locate 全 frame 语义）：主 frame 未中→逐子
  // frame 经 CDP executionContext 求值。子 frame 的 rect 需加 frame 偏移
  // 子 frame 版：label 策略保留（主 frame 版已滤除——禅道外壳 label 同名坑）
  const jsSub = js.replace("/*SKIP_LABEL*/true/**/", "/*SKIP_LABEL*/false/**/");
  try {
    const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: js, returnByValue: true });
    const main = (() => { try { return JSON.parse(r?.result?.value || '{"hit":false}'); }
      catch { return { hit: false }; } })();
    if (main?.hit) return main;
  } catch { /* 主 frame 失败继续子 frame */ }
  try {
    const tree = await chrome.debugger.sendCommand(debuggee, "Page.getFrameTree");
    const frames: any[] = [];
    (function walk(n: any) {
      if (!n?.frame) return;
      frames.push(n.frame);
      for (const c of n.childFrames || []) walk(c);
    })(tree.frameTree);
    // 主 frame 之外的：拿 executionContextId 求值
    await chrome.debugger.sendCommand(debuggee, "Runtime.enable");
    // 逐 frame createIsolatedWorld 或用 contextId——最稳：Runtime.evaluate
    // 的 contextId 从 Runtime.enable 后的事件流拿不到（一次性），
    // 改用 frame 唯一上下文：对每 frame evaluate with contextId=null 不行
    // → 用 Page.createIsolatedWorld(frameId) 拿 contextId
    let frameIndex = -1;  // 子 frame 序（对应页面可见 iframe 列表）
    for (const f of frames) {
      if (!f.parentId) continue; // 跳过主 frame
      frameIndex += 1;
      try {
        // 隐藏 frame 跳过（JeecG 隐藏 iframe 同名"新增"抢先命中实证
        // ——frame 元素级 click 点隐藏按钮无效；隐藏 frame 的
        // innerWidth/Height 为 0）
        const world0 = await chrome.debugger.sendCommand(debuggee,
          "Page.createIsolatedWorld", { frameId: f.id });
        const cid0 = world0?.executionContextId;
        if (cid0 !== undefined) {
          const fv = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
            expression: "window.innerWidth > 0 && window.innerHeight > 0",
            contextId: cid0, returnByValue: true });
          if (fv?.result?.value !== true) continue;
        }
      } catch { /* fail-open */ }
      try {
        const world = await chrome.debugger.sendCommand(debuggee,
          "Page.createIsolatedWorld", { frameId: f.id });
        const cid = world?.executionContextId;
        if (cid === undefined) continue;
        const r2 = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: jsSub, contextId: cid, returnByValue: true });
        const v = (() => { try { return JSON.parse(r2?.result?.value || '{"hit":false}'); }
          catch { return { hit: false }; } })();
        if (v?.hit) {
          v.fromFrame = true;
          v.frameContextId = cid;
          // CDP frame context 的 getBoundingClientRect 已是**主视口坐标**
          // （实证：Playwright bounding_box 与 frame 内求值一致——加偏移
          // 反而点偏 120px，禅道保存按钮实证）。直接用原坐标
          return v;
        }
      } catch { continue; }
    }
  } catch { /* frame 树失败 fail-open */ }
  return { hit: false };
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

// 消息面在 uploader.ts 单一 listener 内分发（MV3 多 listener 的
// sendResponse 竞争会互踩）——本模块只导出函数。


// ---- AH6/AR1 页内场景执行（SW 宿主：CDP 命令活动保活，MV3 不杀） ----

export async function runScenario(
  scenarioId: number,
  onProgress: (msg: string) => void,
  shouldStop?: () => boolean,
  hostTab?: number,
): Promise<{ status: string; steps?: Array<{ step: number; status: string; runId?: number }> }> {
  const scenario = await api(`/scenarios/${scenarioId}`);
  const steps = scenario.steps || [];
  if (!steps.length) return { status: "fail", steps: [] };
  const runTs = Date.now();
  const stepCtx: any[][] = [];
  const results: Array<{ step: number; status: string; runId?: number }> = [];
  for (let i = 0; i < steps.length; i++) {
    if (shouldStop?.()) { onProgress(`已停止：第 ${i + 1} 步前中断`); break; }
    const ovr = resolveStepOverrides(steps[i], stepCtx, runTs);
    onProgress(`步骤 ${i + 1}/${steps.length}：#${steps[i].skill_id} ${steps[i].skill?.name ?? ""} …`);
    try {
      const r = await runSkill(steps[i].skill_id, ovr, onProgress, shouldStop, hostTab);
      stepCtx.push(r.observed || []);
      results.push({ step: i + 1, status: r.status, runId: r.runId });
      onProgress(`步骤 ${i + 1} 完成：${r.status}`);
      if (r.status !== "pass") {
        onProgress(`场景在第 ${i + 1} 步未通过——停止（已执行 ${i + 1}/${steps.length}）`);
        break;
      }
    } catch (e: any) {
      stepCtx.push([]);
      results.push({ step: i + 1, status: "error" });
      onProgress(`步骤 ${i + 1} 失败：${e.message}——停止`);
      break;
    }
  }
  const npass = results.filter((r) => r.status === "pass").length;
  const overall = npass === steps.length && steps.length > 0 ? "pass" : "fail";
  onProgress(`场景执行结束：${npass}/${steps.length} 步通过（${overall}）`);
  return { status: overall, steps: results };
}
