// AG3 扩展执行器（协议客户端）：docs/arch/extension-executor-protocol.md
// 用户在 popup 选择技能并点击执行（含写技能——点击即 C1 授权）。
// SW 步循环：POST /executor/runs/{id}/step 交证据换指令；chrome.debugger
// 执行可信输入；先订阅 Network 后动作（lesson #30 时序）。
export {};

const AGENT = "http://127.0.0.1:8710/api/v1";

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

async function getToken(): Promise<string> {
  if (tokenCache) return tokenCache;
  const { sl_executor_token } = await chrome.storage.local.get("sl_executor_token");
  tokenCache = sl_executor_token || "";
  return tokenCache;
}

async function api(path: string, init?: RequestInit): Promise<any> {
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

export async function listExecutorSkills(): Promise<any[]> {
  return api("/executor/skills");
}

// ---- 执行器主体 ----

interface RunHandle {
  runId: number;
  stop: boolean;
}

const active: RunHandle | null = null;

export async function runSkill(
  skillId: number, overrides: Record<string, string>,
  onProgress: (msg: string) => void,
): Promise<{ status: string }> {
  const plan = await api(`/executor/skills/${skillId}/plan`, {
    method: "POST",
    body: JSON.stringify({ overrides, confirm_side_effect: true }),
  });
  const runId: number = plan.run_id;
  onProgress(`已创建执行 #${runId}（${plan.total_instructions} 条指令）`);

  // 执行页签获取：优先复用已存在的空白页签（CDP 托管浏览器里
  // tabs.create 可能静默 pending——AG0 实证 tabs.query 稳定可用；
  // 宿主页被外部 CDP 持有，attach 会冲突，绝不复用非空白页签）
  let tabId: number | undefined;
  try {
    const all = await chrome.tabs.query({});
    const blank = all.find((t) => !t.url || t.url === "about:blank");
    if (blank?.id) {
      tabId = blank.id;
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
    const debuggee = { tabId };
  try {
    await chrome.debugger.attach(debuggee, "1.3");
      } catch (e: any) {
    await api(`/executor/runs/${runId}/finish`, {
      method: "POST",
      body: JSON.stringify({ status: "fail", summary: { error: `attach 失败：${e.message}（关闭 DevTools 后重试）` } }),
    });
    await chrome.tabs.remove(tabId).catch(() => {});
    return { status: "fail" };
  }
  onProgress("已 attach（顶部横幅=执行中，全程可见）");

  // 网络证据：先订阅后动作（lesson #30）
  const networkLog: any[] = [];
  chrome.debugger.onEvent.addListener(function onEvt(source, method, params: any) {
    if (source.tabId !== tabId) return;
    if (method === "Network.responseReceived") {
      networkLog.push({
        url: params?.response?.url, status: params?.response?.status,
        requestId: params?.requestId,
        method: params?.type || "",
      });
    }
  });
  await chrome.debugger.sendCommand(debuggee, "Network.enable").catch(() => {});

  const t0 = Date.now();
  let instruction: Instruction | null = plan.instruction;
  let steps = 0;
  try {
    while (instruction && instruction.op !== "detach") {
      const ev = await execute(debuggee, tabId, instruction, networkLog, onProgress);
      steps++;
      // AG3：步 POST 加 8s race——任何卡点浮出为错误而非静默挂死
      const resp = await Promise.race([
        api(`/executor/runs/${runId}/step`, {
          method: "POST",
          body: JSON.stringify(ev),
        }),
        new Promise<never>((_, rej) =>
          setTimeout(() => rej(new Error(`step POST 挂起 seq=${ev.seq}`)), 8000)),
      ]);
      instruction = resp.instruction;
    }
    await chrome.debugger.sendCommand(debuggee, "Page.enable").catch(() => {});
    const title = await pageTitle(debuggee);
    const finish = await api(`/executor/runs/${runId}/finish`, {
      method: "POST",
      body: JSON.stringify({
        status: "done",
        summary: {
          executed: [], observed: networkLog.filter((n) => n.url && n.url.startsWith("http")),
          duration_ms: Date.now() - t0, page_title: title, steps,
        },
      }),
    });
    onProgress(`完成：${finish.status}（${steps} 步）`);
    return { status: finish.status };
  } catch (e: any) {
    onProgress(`中断：${e.message}`);
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
    await chrome.debugger.detach(debuggee).catch(() => {});
    await chrome.tabs.remove(tabId).catch(() => {});
  }
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
): Promise<{ seq: number; result: string; evidence: any }> {
  const evidence: any = { network: [], toasts: [] };
  if (ins.op === "goto") {
    onProgress(`导航 ${ins.url}`);
    await chrome.debugger.sendCommand(debuggee, "Page.enable").catch(() => {});
    await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: ins.url });
    await sleep(2500);
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "snapshot") {
    const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: "JSON.stringify({url: location.href, title: document.title})",
      returnByValue: true,
    });
    try { evidence.page = JSON.parse(r?.result?.value || "{}"); } catch { /* noop */ }
    onProgress(`快照（${ins.phase}）`);
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "click" || ins.op === "fill") {
    const label = ins.label || ins.name || "";
    const resolved = await resolve(debuggee, ins, label);
    if (!resolved?.hit) {
      onProgress(`定位失败：${label}（触发服务端介入）`);
      return { seq: ins.seq, result: "miss", evidence: { ...evidence, miss: label } };
    }
    const { rect } = resolved;
    const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mousePressed", x, y, button: "left", clickCount: 1 });
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseReleased", x, y, button: "left", clickCount: 1 });
    if (ins.op === "fill" && ins.value !== undefined) {
      await chrome.debugger.sendCommand(debuggee, "Input.insertText", { text: String(ins.value) });
      await sleep(400);
      // 水合确认（lesson #15 语义）：读回值
      const v = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(() => {
          const els = document.querySelectorAll('input, textarea');
          for (const el of els) if (el.value === ${JSON.stringify(ins.value)}) return el.value;
          return '';
        })()`, returnByValue: true });
      evidence.value_after = v?.result?.value || "";
    }
    onProgress(`${ins.op} ${label}${resolved.strategy ? `（${resolved.strategy}）` : ""}`);
    return { seq: ins.seq, result: "ok", evidence };
  }
  // 未知指令：如实上报，服务端决定
  return { seq: ins.seq, result: "unsupported", evidence };
}

async function resolve(debuggee: any, ins: Instruction, label: string): Promise<any> {
  const cands = ins.resolve_candidates || [];
  const js = `(function() {
    const candidates = ${JSON.stringify(cands)};
    const label = ${JSON.stringify(label)};
    const visible = (el) => { if (!el.isConnected) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0; };
    for (const c of candidates) {
      let els = [];
      try {
        if (c.kind === "role") {
          els = [...document.querySelectorAll('[role="button"], button')]
            .filter(el => visible(el) && (el.textContent||'').trim() === label);
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
        } else {
          els = [...document.querySelectorAll(c.selector)].filter(visible);
        }
      } catch (e) { continue; }
      if (els.length === 1) {
        const r = els[0].getBoundingClientRect();
        return {hit: true, strategy: c.strategy,
          rect: {x: r.x, y: r.y, width: r.width, height: r.height}};
      }
    }
    return {hit: false};
  })()`;
  const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
    expression: js, returnByValue: true });
  try { return JSON.parse(r?.result?.value || '{"hit":false}'); } catch { return { hit: false }; }
}

function sleep(ms: number): Promise<void> {
  return new Promise((res) => setTimeout(res, ms));
}

// 消息面在 uploader.ts 单一 listener 内分发（MV3 多 listener 的
// sendResponse 竞争会互踩）——本模块只导出函数。

