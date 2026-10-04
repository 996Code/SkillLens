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
  shouldStop?: () => boolean,
): Promise<{ status: string; runId?: number }> {
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

  // 网络证据：先订阅后动作（lesson #30）；AG4 补响应体（断言原料）
  const networkLog: any[] = [];
  const pendingBodies = new Map<string, string>();
  chrome.debugger.onEvent.addListener(function onEvt(source, method, params: any) {
    if (source.tabId !== tabId) return;
    if (method === "Network.requestWillBeSent") {
      pendingBodies.set(params?.requestId, params?.request?.method || "GET");
      return;
    }
    if (method === "Network.responseReceived") {
      const url: string = params?.response?.url || "";
      networkLog.push({
        url, status: params?.response?.status,
        requestId: params?.requestId,
        method: pendingBodies.get(params?.requestId) || "GET", body: "",
      });
      // 响应体异步取（AG0 实证 Network.getResponseBody 可用；失败留空）
      const idx = networkLog.length - 1;
      chrome.debugger.sendCommand(debuggee, "Network.getResponseBody", {
        requestId: params?.requestId,
      }).then((b: any) => {
        networkLog[idx].body = (b?.body || "").slice(0, 102400);
      }).catch(() => { /* 已导航/流式体不可取——留空不阻塞 */ });
    }
  });
  await chrome.debugger.sendCommand(debuggee, "Network.enable").catch(() => {});

  const t0 = Date.now();
  let instruction: Instruction | null = plan.instruction;
  let steps = 0;
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
      const ev = await execute(debuggee, tabId, instruction, networkLog, onProgress);
      steps++;
      // 导航失败即中止（错误页上的后续步骤是假执行——UX 评审致命 2）
      if (ev.result === "error") {
        await Promise.race([
          api(`/executor/runs/${runId}/step`, {
            method: "POST", body: JSON.stringify(ev) }),
          new Promise((res) => setTimeout(res, 8000)),
        ]).catch(() => {});
        await Promise.race([
          api(`/executor/runs/${runId}/finish`, {
            method: "POST",
            body: JSON.stringify({ status: "fail",
              summary: { error: ev.evidence?.error || "导航失败",
                         executed: [], observed: [] } }) }),
          new Promise((res) => setTimeout(res, 8000)),
        ]).catch(() => {});
        onProgress(`中止：${ev.evidence?.error || "导航失败"}`);
        return { status: "fail" };
      }
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
    return { status: finish.status, runId };
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
    await sleep(2500);
    try {
      const u = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: "location.href", returnByValue: true });
      const finalUrl = String(u?.result?.value || "");
      onProgress(`导航后实际页面: ${finalUrl.slice(0, 60)}`);
      // 目标站不可达判定（UX 评审致命 2：chrome-error 页仍判 pass）——
      // 导航落错误页即中止，如实 fail
      if (finalUrl.startsWith("chrome-error://") || finalUrl === "about:blank") {
        return { seq: ins.seq, result: "error",
                 evidence: { ...evidence, error: `目标站不可达: ${ins.url}` } };
      }
    } catch { /* fail-open */ }
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "snapshot") {
    // 证据链对齐服务端（S33）：before/after 页面快照（采集端同 schema
    // 精简版——forms 带脱敏）+ 截图（base64，服务端落盘 artifacts）
    try {
      const r = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `JSON.stringify((function(){
          const forms = [...document.querySelectorAll('input, select, textarea')]
            .filter(e => e.getBoundingClientRect().width > 0)
            .slice(0, 30).map(e => ({
              label: ((e.closest('.form-group, .ant-form-item, .cgf-item') || {})
                .querySelector ? e.closest('.form-group, .ant-form-item, .cgf-item')
                  .querySelector('label')?.textContent : '') || e.placeholder || e.name || '',
              value: e.type === 'password' ? '[REDACTED]' : String(e.value || '')}))
            .map(f => ({label: String(f.label || '').trim().slice(0, 40),
                        value: String(f.value || '').slice(0, 60)}));
          const toasts = [...document.querySelectorAll(
            '.toast, .toast-message, .ant-message-notice, .el-message, [role=alert]')]
            .filter(e => e.offsetParent !== null)
            .map(e => (e.textContent || '').trim().slice(0, 80)).filter(Boolean);
          return {url: location.href, title: document.title, forms, toasts};
        })())`, returnByValue: true });
      try { evidence.page = JSON.parse(r?.result?.value || "{}"); } catch { /* noop */ }
    } catch { /* fail-open */ }
    try {
      const shot = await chrome.debugger.sendCommand(debuggee, "Page.captureScreenshot",
        { format: "png" });
      evidence.screenshot = String(shot?.data || "").slice(0, 300000);
    } catch { /* fail-open */ }
    onProgress(`快照（${ins.phase}）`);
    return { seq: ins.seq, result: "ok", evidence };
  }
  if (ins.op === "click" || ins.op === "fill") {
    const label = ins.label || ins.name || "";
    // fill 直通 JS 设值（官方 harness 本质：data-fieldname/placeholder/
    // form-item label 三级查找+input 事件派发——ERPNext 234 PASS 实证；
    // resolver 候选对 fill 的 form-group 命中错元素/多元素 miss 实证）
    if (ins.op === "fill" && ins.value !== undefined) {
      // 直通+重试（模态/抽屉渲染窗口——JeecG 新增点击后模态 1-2s 才开，
      // 首次查找空实证）
      let setVal: any = null;
      for (let tryN = 0; tryN < 3; tryN++) {
        setVal = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: `(function(){
            const label = ${JSON.stringify(label)};
            let target = null;
            const df = document.querySelector('[data-fieldname="' + label + '"] input');
            if (df && df.getBoundingClientRect().width > 0) target = df;
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
              const bare = label.replace(/[*\\s]/g, '');
              const groups = [...document.querySelectorAll(
                '.ant-form-item, .cgf-item, .form-group')];
              for (const g of groups) {
                const lbl = (g.querySelector('label')?.textContent || '')
                  .replace(/[*\\s]/g, '');
                if (lbl === bare) {
                  const inp = g.querySelector('input');
                  if (inp && inp.getBoundingClientRect().width > 0) { target = inp; break; }
                }
              }
            }
            if (!target) return '';
            const setter = Object.getOwnPropertyDescriptor(
              window.HTMLInputElement.prototype, 'value').set;
            setter.call(target, ${JSON.stringify(String(ins.value))});
            target.dispatchEvent(new Event('input', {bubbles: true}));
            target.dispatchEvent(new Event('change', {bubbles: true}));
            return target.value;
          })()`, returnByValue: true });
        if (setVal?.result?.value) break;
        await sleep(2000);
      }
      const val = setVal?.result?.value || "";
      if (val) {
        await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
          expression: "(document.activeElement || {}).blur && document.activeElement.blur()" })
          .catch(() => {});
        await sleep(300);
        onProgress(`fill ${label}（JS 设值）`);
        return { seq: ins.seq, result: "ok", evidence: { network: [], toasts: [], value_after: val } };
      }
      // JS 设值未命中——落回 resolver 路径（重试+介入）
    }
    // 对齐 locate 语义：异步渲染重试（服务端 12 轮×1s；插件端 8 轮×1s
    // ——首版真机实证：goto 后 2.5s 禅道 iframe/JeecG 列表未渲染完即 miss；
    // 第 4 轮插一次 reload——SPA 视图状态病（Odoo kanban/list 记忆等）
    // 重载即愈，服务端新 tab 无此病史）
    let resolved: any = null;
    for (let attempt = 0; attempt < 8; attempt++) {
      resolved = await resolve(debuggee, ins, label, onProgress);
      if (resolved?.hit) break;
      if (attempt === 3) {
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
    // row-trigger：scrollIntoView 后坐标 trusted click（元素级 el.click()
    // 不开 ant-dropdown——React 需可信事件；服务端 click(force) 也是 CDP
    // trusted。scroll 实证有效：cx 1439→1212 入视口）
    // scrollIntoView 先行：行操作触发器常在视口右缘外（AG5 铁证：
    // rect.x=1409 > 视口 1280——坐标点击全落空）。滚入后重取 rect。
    // row-anchor 场景按 anchor+label 行内定位（与坐标重取同源——SW
    // 复刻实证该链路开菜单）
    try {
      const anchorJson = JSON.stringify(resolved.anchorTxt || "");
      const req = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const label = ${JSON.stringify(ins.label || ins.name || "")};
          const anchor = ${anchorJson};
          let el = null;
          if (anchor) {
            const rows = [...document.querySelectorAll('.ant-table-row, .list-item, .grid-row, tr')]
              .filter(r => (r.textContent || '').includes(anchor));
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
                .filter(r => (r.textContent || '').includes(anchor));
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
    // 保存/确定类点击+模态开着：模态 footer primary 优先（JeecG 实证
    // 保存步 ok 但 addAll 未发——点中列表页同名按钮；官方 harness 模式
    // =模态上下文的提交按钮）
    if (ins.op === "click" && /保存|确定|提\s*交/.test(label)) {
      const modalBtn = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: `(function(){
          const modal = document.querySelector('.ant-modal-content, .ant-drawer-content');
          if (!modal || modal.getBoundingClientRect().width === 0) return '';
          const btns = [...modal.querySelectorAll('button')]
            .filter(e => /保存|确定|提\\s*交/.test((e.textContent||'').trim())
              && e.getBoundingClientRect().width > 0);
          if (btns.length) { btns[0].click(); return 'ok'; }
          return '';
        })()`, returnByValue: true });
      if (modalBtn?.result?.value === "ok") {
        await sleep(2000);
        onProgress(`click ${label}（模态提交）`);
        return { seq: ins.seq, result: "ok", evidence };
      }
    }
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
    // hover 先行：mouseenter 态组件先展开；随后正常 click（服务端
    // row-trigger 即 JS click——ant-dropdown 的 onClick 含 open 逻辑，
    // hover-only 假设被服务端 pass 行为证伪）
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseMoved", x, y });
    await sleep(800);
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
          const df = document.querySelector(
            '[data-fieldname="' + label + '"] input');
          if (df && df.getBoundingClientRect().width > 0) target = df;
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
            // 与 form-item label 文本匹配，取组内 input）
            const bare = label.replace(/[*\s]/g, '');
            const groups = [...document.querySelectorAll(
              '.ant-form-item, .cgf-item, .form-group')];
            for (const g of groups) {
              const lbl = (g.querySelector('label')?.textContent || '')
                .replace(/[*\s]/g, '');
              if (lbl === bare) {
                const inp = g.querySelector('input');
                if (inp && inp.getBoundingClientRect().width > 0) { target = inp; break; }
              }
            }
          }
          if (!target) return '';
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
          setter.call(target, ${JSON.stringify(String(ins.value))});
          target.dispatchEvent(new Event('input', {bubbles: true}));
          target.dispatchEvent(new Event('change', {bubbles: true}));
          return target.value;
        })()`, returnByValue: true });
      evidence.value_after = setVal?.result?.value || "";
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
    for (const c of candidates) {
      let els = [];
      try {
        if (c.kind === "role") {
          const all = [...document.querySelectorAll('[role="button"], button')]
            .filter(el => visible(el) && (el.textContent||'').trim() === label);
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
          const rows = [...document.querySelectorAll(c.selector)]
            .filter(r => (r.textContent || "").includes(c.anchor || ""));
          for (const row of rows) {
            const trig = [...row.querySelectorAll("a, span, button, [role=button]")]
              .filter(el => visible(el) && (el.textContent || "").trim() === label);
            if (trig.length) { els = [trig[0]]; rowAnchor = c.anchor || ""; break; }
          }
        } else {
          els = [...document.querySelectorAll(c.selector)].filter(visible);
        }
      } catch (e) { continue; }
      // role 精确匹配放宽：多个同名可见按钮时取第一个（ERPNext Save
      // 实证 texts 有 Save 但唯一性判定 miss——主按钮通常文档序最前）
      if (els.length === 1 || (els.length > 1 && c.kind === "role")) {
        const r = els[0].getBoundingClientRect();
        return {hit: true, strategy: c.strategy, tagCls: (els[0].className || ""),
          tagName: (els[0].tagName || "").toLowerCase(),
          anchorTxt: rowAnchor || "",
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
    const enabled = await chrome.debugger.sendCommand(debuggee, "Runtime.enable");
    const ctxs: any[] = enabled?.executionContextCreated
      ? [enabled.executionContextCreated] : [];
    // 逐 frame createIsolatedWorld 或用 contextId——最稳：Runtime.evaluate
    // 的 contextId 从 Runtime.enable 后的事件流拿不到（一次性），
    // 改用 frame 唯一上下文：对每 frame evaluate with contextId=null 不行
    // → 用 Page.createIsolatedWorld(frameId) 拿 contextId
    let frameIndex = -1;  // 子 frame 序（对应页面可见 iframe 列表）
    for (const f of frames) {
      if (!f.parentId) continue; // 跳过主 frame
      frameIndex += 1;
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

