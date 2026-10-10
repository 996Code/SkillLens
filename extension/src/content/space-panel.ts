// AH4b 油猴式悬浮空间面板：注入目标系统页面的 shadow DOM 面板。
// 与独立窗（space.html）的差异：随页面存活（popup 生命周期问题根治）、
// 系统识别直接用 location.href、视线不离业务页。执行仍走 executor.html
// 独立页（AG3 稳态架构不变——面板只做选择/组链/发起/状态）。
// 幂等守卫同 capture（SW 程序化注入可能重复执行本模块）。
const wp = window as unknown as { __skilllens_panel?: boolean };
if (wp.__skilllens_panel) {
  throw new Error("[skilllens] panel already injected");
}
wp.__skilllens_panel = true;

const HOST_ID = "skilllens-space-host";

import { describeFailure } from "../shared/failures";

function mount(): void {
  if (document.getElementById(HOST_ID)) return;
  const host = document.createElement("div");
  host.id = HOST_ID;
  host.setAttribute("data-skilllens-ui", "space-panel");
  host.style.cssText = "position:fixed; top:16px; right:16px; z-index:2147483647;";
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; margin: 0; }
      .panel {
        width: 340px; max-height: 70vh; display: flex; flex-direction: column;
        background: #fff; border: 1px solid #e5e7eb; border-radius: 14px;
        box-shadow: 0 8px 30px rgba(0,0,0,.18);
        font: 13px/1.5 -apple-system, "Segoe UI", system-ui, sans-serif; color: #1a2233;
        overflow: hidden;
      }
      .panel.collapsed { max-height: none; width: auto; }
      .bar {
        display: flex; align-items: center; gap: 8px; padding: 10px 12px;
        background: linear-gradient(135deg,#2563eb,#7c3aed); color: #fff;
        cursor: move; user-select: none;
      }
      .bar .logo { font-weight: 700; font-size: 12px; }
      .bar .sys { font-size: 11px; opacity: .9; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .bar button {
        background: rgba(255,255,255,.2); color: #fff; border: none; border-radius: 6px;
        font: inherit; font-size: 11px; padding: 2px 8px; cursor: pointer;
      }
      .bar button:hover { background: rgba(255,255,255,.35); }
      .rec-dot { width:8px; height:8px; border-radius:50%; background:#d1d5db; }
      .rec-dot.on { background:#f87171; animation: pulse 1.2s ease-in-out infinite; }
      @keyframes pulse { 0%,100%{box-shadow:0 0 0 0 rgba(248,113,113,.5)} 50%{box-shadow:0 0 0 5px rgba(248,113,113,0)} }
      .body { padding: 10px 12px; overflow-y: auto; min-height: 0; }
      .collapsed .body, .collapsed .foot { display: none; }
      .lbl { font-size: 11px; color: #6b7280; margin-bottom: 6px; }
      input.q {
        width: 100%; padding: 6px 10px; font: inherit; font-size: 12px;
        border: 1px solid #e5e7eb; border-radius: 8px; outline: none; margin-bottom: 6px;
      }
      input.q:focus { border-color: #2563eb; }
      .sk {
        display: flex; align-items: center; gap: 6px; padding: 5px 4px;
        border-bottom: 1px solid #f1f3f5; cursor: pointer; font-size: 12px;
      }
      .sk:hover { background: #f0f6ff; }
      .sk.on { background: #e8f0fe; }
      .sk .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .sk .w { font-size: 10px; color: #dc2626; }
      .sk .o { color: #2563eb; font-weight: 700; font-size: 11px; width: 14px; }
      .sk .one {
        font-size: 11px; border: none; border-radius: 5px; padding: 2px 8px;
        cursor: pointer; background: #2563eb; color: #fff; display: none;
      }
      .sk:hover .one { display: inline-block; }
      .picked { background: #f7f8fa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 8px; margin-top: 8px; font-size: 12px; }
      .picked .st { color: #6b7280; font-size: 11px; margin-bottom: 6px; }
      .picked .ovr { margin: 4px 0; display: flex; gap: 4px; align-items: center; }
      .picked .ovr select {
        flex: 1; font: inherit; font-size: 11px; padding: 3px 4px;
        border: 1px solid #e5e7eb; border-radius: 5px; background: #fff;
      }
      .picked .ovr input {
        flex: 1.2; font: inherit; font-size: 11px; padding: 3px 6px;
        border: 1px solid #e5e7eb; border-radius: 5px;
      }
      .picked .ovr .del { border: none; background: none; color: #dc2626; cursor: pointer; font-size: 12px; }
      .picked .addf { font-size: 11px; border: 1px dashed #cbd5e1; background: none; border-radius: 5px; padding: 2px 8px; cursor: pointer; color: #6b7280; }
      .picked .rules { font-size: 10px; color: #6b7280; margin-top: 3px; }
      .picked .rules code { background: #eef2f7; border-radius: 3px; padding: 0 3px; cursor: pointer; }
      .picked .row { display: flex; gap: 6px; }
      .picked input.nm { flex: 1; padding: 5px 8px; font: inherit; font-size: 12px; border: 1px solid #e5e7eb; border-radius: 6px; outline: none; }
      .picked button {
        font: inherit; font-size: 12px; font-weight: 500; border: none;
        border-radius: 6px; padding: 5px 12px; cursor: pointer;
      }
      .go { background: #2563eb; color: #fff; }
      .go:hover { background: #1d4ed8; }
      .sv { background: #eef2f7; color: #1a2233; }
      .ch { display: flex; align-items: center; gap: 6px; padding: 4px 2px; border-bottom: 1px solid #f1f3f5; font-size: 12px; }
      .ch .nm { flex: 1; }
      .ch .m { font-size: 10px; color: #6b7280; }
      .ch button { font-size: 11px; border: none; border-radius: 5px; padding: 2px 8px; cursor: pointer; }
      .ch .run { background: #2563eb; color: #fff; }
      .ch .del { color: #dc2626; background: none; }
      .empty { color: #6b7280; font-size: 12px; padding: 4px 0; }
      .note { padding: 8px 12px; font-size: 12px; border-top: 1px solid #f1f3f5; display: none; }
      .prog { padding: 8px 12px; border-top: 1px solid #e5e7eb; background: #f8fafc; }
      .prog .pg-t { font-size: 12px; font-weight: 600; color: #2563eb; }
      .prog .pg-l { font-size: 11px; color: #6b7280; max-height: 90px; overflow-y: auto;
                    font-family: Consolas, monospace; white-space: pre-wrap; margin-top: 4px; }
      .note.ok { color: #16a34a; }
      .note.err { color: #dc2626; }
      .foot { padding: 6px 12px 10px; }
      .sec-t { font-size: 11px; color: #6b7280; margin: 8px 0 4px; }
    </style>
    <div class="panel" id="pn">
      <div class="bar" id="bar">
        <span class="logo">SL 空间</span>
        <span class="rec-dot" id="recdot" title="未在录制"></span>
        <span class="sys" id="sys">识别系统中…</span>
        <button id="fold" title="收起/展开">—</button>
        <button id="close" title="关闭">×</button>
      </div>
      <div class="body">
        <div class="lbl">本系统回放（点选组链，按点击顺序）</div>
        <input class="q" id="q" placeholder="搜索技能名…" />
        <div id="list"><div class="empty">加载中…</div></div>
        <div class="picked" id="pk" style="display:none">
          <div class="st" id="pks"></div>
          <input class="nm" id="cn" placeholder="链名称（如：建表单+发数据）" />
          <div class="row" style="margin-top:6px">
            <button class="go" id="go">立即执行</button>
            <button class="sv" id="sv">保存为链</button>
          </div>
        </div>
        <div class="sec-t">已保存的链</div>
        <div id="chs"><div class="empty">无</div></div>
      </div>
      <div class="note" id="nt"></div>
      <div class="prog" id="pg" style="display:none">
        <div class="pg-t" id="pgt">执行中…</div>
        <div class="pg-l" id="pgl"></div>
      </div>
      <div class="foot"></div>
    </div>
  `;
  document.documentElement.appendChild(host);

  // ---- 拖动 ----
  const bar = root.getElementById("bar")!;
  const hostEl = host;
  let drag: { x: number; y: number; l: number; t: number } | null = null;
  bar.addEventListener("mousedown", (e) => {
    if ((e.target as HTMLElement).tagName === "BUTTON") return;
    drag = { x: e.clientX, y: e.clientY,
             l: hostEl.offsetLeft, t: hostEl.offsetTop };
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    hostEl.style.left = `${Math.max(0, drag.l + e.clientX - drag.x)}px`;
    hostEl.style.top = `${Math.max(0, drag.t + e.clientY - drag.y)}px`;
    hostEl.style.right = "auto";
  });
  window.addEventListener("mouseup", () => { drag = null; });

  root.getElementById("close")!.addEventListener("click", () => host.remove());
  // 系统隔离切换：默认仅本系统（隔离）；点系统名查看全部（跨系统对照）
  // 注：sysEl 等 DOM 引用须在事件绑定前定义（TDZ——定义前同步访问会
  // ReferenceError 中断 mount，面板挂一半永卡"识别系统中…"模板初值）
  const sysEl = root.getElementById("sys")!;
  sysEl.addEventListener("click", () => {
    showAllSystems = !showAllSystems;
    sysEl.textContent = showAllSystems
      ? `全部系统（当前：${systemName || "未识别"}）` : (systemName || "未识别系统");
    void loadSkills();
  });
  root.getElementById("fold")!.addEventListener("click", () => {
    root.getElementById("pn")!.classList.toggle("collapsed");
  });

  // ---- 数据与渲染（逻辑与 space.ts 同源：面板复用同一组 API） ----
  const AGENT = "http://127.0.0.1:8710/api/v1";
  const listEl = root.getElementById("list")!;
  const qEl = root.getElementById("q") as HTMLInputElement;
  const pkEl = root.getElementById("pk")!;
  const pksEl = root.getElementById("pks")!;
  const cnEl = root.getElementById("cn") as HTMLInputElement;
  const chsEl = root.getElementById("chs")!;
  const ntEl = root.getElementById("nt")!;

  let systemName = "";
  let skills: any[] = [];
  let picked: any[] = [];
  // AI2 overrides 编辑态：picked[i].__ovr = Record<key, value>；
  // __fills = 该技能 fill 候选（懒加载——点选时拉 /chains/fills/{id}）
  const fillsCache = new Map<number, Array<{ name: string; value: string }>>();

  async function loadFills(skillId: number): Promise<Array<{ name: string; value: string }>> {
    if (fillsCache.has(skillId)) return fillsCache.get(skillId)!;
    try {
      const r = await api(`/chains/fills/${skillId}`);
      fillsCache.set(skillId, Array.isArray(r) ? r : []);
    } catch (e) {
      // AK6 批次3：fill 候选加载失败留痕（决策相关——静默空会让链换参
      // 编辑降级为不可用且无因可查）；分类走四码（failures.ts）
      const f = describeFailure(e);
      console.warn(`[SL] fills 加载失败 skill=${skillId} [${f.code}] ${f.plain}`);
      fillsCache.set(skillId, []);
    }
    return fillsCache.get(skillId)!;
  }

  // AH6b port 通道执行：connect 长连接（sendMessage/storage 在 CDP 环境
  // 均不可靠的第三替代）；进度双向走 port——面板即控制台，无跳板
  function execViaPort(req: { skillId?: number; chainId?: number }): void {
    const pg = root.getElementById("pg")!;
    const pgt = root.getElementById("pgt")!;
    const pgl = root.getElementById("pgl")!;
    const fallbackUrl = () => chrome.runtime.getURL(req.skillId != null
      ? `executor.html?skill=${req.skillId}&auto=1`
      : `executor.html?chain=${req.chainId}&auto=1`);
    try {
      const port = chrome.runtime.connect({ name: "skilllens-exec" });
      let alive = false;
      port.onMessage.addListener((m: any) => {
        if (m?.type === "SL_PONG") { alive = true; return; }
        if (m?.type !== "SL_PROGRESS") return;
        const line = `[${new Date().toTimeString().slice(0, 8)}] ${m.msg}`;
        pgl.textContent += line + "\n";
        pgl.scrollTop = pgl.scrollHeight;
        if (String(m.msg).includes("链执行结束") || String(m.msg).includes("完成：")) {
          const ok = String(m.msg).includes("pass");
          pgt.textContent = ok ? "执行完成（通过）" : "执行结束（未通过）";
          pgt.style.color = ok ? "#16a34a" : "#dc2626";
        }
      });
      // pong 探测：1.5s 无回执=port 断（CDP 托管环境实测全断）——自动回退
      // 执行页；真 Chrome port 直达：面板即控制台，无跳板
      setTimeout(() => {
        if (!alive) {
          try { port.disconnect(); } catch { /* 已断 */ }
          note("本页直执行通道不可用——已打开执行页（自动执行）", "err");
          window.open(fallbackUrl(), "_blank");
          return;
        }
        pg.style.display = "block";
        pgt.style.color = "#2563eb";
        pgt.textContent = "执行中…";
        pgl.textContent = "";
        port.postMessage({ type: "EXEC_RUN", ...req });
        note("已发起执行（本页驱动，进度见下方）", "ok");
      }, 1500);
    } catch {
      window.open(fallbackUrl(), "_blank");
    }
  }

  function renderPicked(): void {
    pkEl.style.display = picked.length ? "block" : "none";
    pksEl.replaceChildren();
    picked.forEach((p, i) => {
      const row = document.createElement("div");
      row.style.cssText = "margin:4px 0;padding:4px;border-bottom:1px solid #eef2f7";
      const head = document.createElement("div");
      head.style.cssText = "display:flex;align-items:center;gap:4px";
      const no = document.createElement("b");
      no.style.color = "#2563eb";
      no.textContent = `${i + 1}.`;
      const nm = document.createElement("span");
      nm.style.flex = "1";
      nm.textContent = p.name;
      const add = document.createElement("button");
      add.className = "addf";
      add.textContent = "+参数";
      add.addEventListener("click", async () => {
        const fills = await loadFills(p.id);
        if (!fills.length) { note("该技能无 fill 字段（无可换参项）", "err"); return; }
        // AI5 unique 推荐：疑似唯一字段（sl_*/长数字形态）直接建议规则值
        // ——一键采纳防撞名（服务端 recommend 同源逻辑的前端轻量版）
        p.__ovr = { ...(p.__ovr || {}) };
        let added = 0;
        for (const f of fills) {
          if (p.__ovr[f.name] != null) continue;
          const uniq = /^(?:[a-z]+_)?(?:sl_|test_|t\d|[0-9]{6,})/i.test(f.value || "");
          p.__ovr[f.name] = uniq
            ? `${"${unique:"}${(f.value || "").replace(/[a-zA-Z]?[0-9]+$/, "")}}"`
            : "";
          added++;
        }
        if (!added) { note("参数已全部添加", "err"); return; }
        renderPicked();
      });
      head.append(no, nm, add);
      row.append(head);

      const ovr = p.__ovr || {};
      for (const [k, v] of Object.entries(ovr)) {
        const line = document.createElement("div");
        line.className = "ovr";
        const sel = document.createElement("select");
        void loadFills(p.id).then((fills) => {
          sel.replaceChildren();
          for (const f of fills) {
            const o = document.createElement("option");
            o.value = f.name;
            o.textContent = f.name;
            if (f.value) o.textContent += `（原:${f.value.slice(0, 12)}）`;
            if (f.name === k) o.selected = true;
            sel.append(o);
          }
          if (!fills.some((f) => f.name === k)) {
            const o = document.createElement("option");
            o.value = k; o.textContent = `${k} ⚠不在候选`; o.selected = true;
            sel.append(o);
          }
        });
        sel.addEventListener("change", () => {
          const old = { ...p.__ovr };
          delete old[k];
          p.__ovr = { ...old, [sel.value]: v };
          renderPicked();
        });
        const inp = document.createElement("input");
        inp.value = v;
        inp.placeholder = "值或 ${unique:前缀} / ${stepN.字段}";
        inp.addEventListener("input", () => { p.__ovr[k] = inp.value; });
        const del = document.createElement("button");
        del.className = "del"; del.textContent = "×";
        del.addEventListener("click", () => {
          delete p.__ovr[k];
          renderPicked();
        });
        line.append(sel, inp, del);
        row.append(line);
      }
      if (Object.keys(ovr).length) {
        const hint = document.createElement("div");
        hint.className = "rules";
        hint.innerHTML =
          `规则：<code title="点击插入">${"$" + "{unique:前缀}"}</code> 每次唯一 ` +
          `<code title="点击插入">${"$" + "{step" + (i) + ".字段}"}</code> 取本步上游产出`;
        const codes = hint.querySelectorAll("code");
        const lastInput = row.querySelector<HTMLInputElement>(".ovr input:last-of-type");
        codes.forEach((c) => c.addEventListener("click", () => {
          if (lastInput) { lastInput.value = c.textContent || ""; lastInput.dispatchEvent(new Event("input")); }
        }));
        row.append(hint);
      }
      pksEl.append(row);
    });
  }

  function note(msg: string, cls: "ok" | "err"): void {
    ntEl.style.display = "block";
    ntEl.className = `note ${cls}`;
    ntEl.textContent = msg;
    setTimeout(() => { ntEl.style.display = "none"; }, 4000);
  }

  // token 直读 storage（content script 有 chrome.storage 权限——不经 SW
  // 消息，多 listener 通道竞争在 CDP 托管浏览器下不可靠的教训）
  async function token(): Promise<string> {
    // storage 读加 2s race——CDP 托管环境 chrome.storage 在 CS 世界实测
    // 挂起（detectSystem 永卡"识别系统中"）；超时按空 token 走 401→登录
    try {
      return await Promise.race([
        chrome.storage.local.get("sl_executor_token") as Promise<{
          sl_executor_token?: string }>,
        new Promise<{ sl_executor_token?: string }>((res) =>
          setTimeout(() => res({}), 2000)),
      ]).then((r) => r.sl_executor_token || "");
    } catch { return ""; }
  }

  async function detectSystem(): Promise<void> {
    sysEl.textContent = "读 token…";
    let t = await token();
    let r: Response | null = null;
    for (let attempt = 0; attempt < 2; attempt++) {
      sysEl.textContent = "识别系统…";
      try {
        r = await Promise.race([
          fetch(`${AGENT}/adapters/match?url=${encodeURIComponent(location.href)}`,
            { headers: { Authorization: `Bearer ${t}` } }) as Promise<Response>,
          new Promise<never>((_, rej) =>
            setTimeout(() => rej(new Error("match 超时")), 5000)),
        ]);
      } catch (e: any) {
        sysEl.textContent = `Agent 未连（${String(e?.message || e).slice(0, 30)}）`;
        return;
      }
      if (r.status !== 401) break;
      // 401→自动换 token 重试一次（内部部署免登录）；换不到则提示
      const tk = await autoSession();
      if (!tk) {
        sysEl.textContent = "未授权（server 开 PLUGIN_TRUST=1 免登录）";
        return;
      }
      t = tk;
    }
    try {
      if (!r || !r.ok) throw new Error(`HTTP ${r && r.status}`);
      const m = await r.json();
      systemName = m.system || "";
      sysEl.textContent = systemName || "未识别系统";
    } catch (e: any) {
      sysEl.textContent = `Agent 未连（${String(e?.message || e).slice(0, 30)}）`;
    }
  }

  // 内部部署免登录：401 时自动经 plugin-session 换 token（无凭据传输，
  // server 侧 PLUGIN_TRUST=1 开关控制）；换不到才提示。登录表单已删
  // （内部使用不设登录门槛）。
  async function autoSession(): Promise<string> {
    try {
      const r = await fetch(`${AGENT}/auth/plugin-session`, {
        method: "POST",
        headers: { "X-SkillLens-Agent": "1" },
      });
      if (!r.ok) return "";
      const { token: tk } = await r.json();
      if (tk) await chrome.storage.local.set({ sl_executor_token: tk });
      return tk || "";
    } catch { return ""; }
  }

  function render(): void {
    const q = qEl.value.trim().toLowerCase();
    listEl.replaceChildren();
    if (!skills.length) {
      const d = document.createElement("div");
      d.className = "empty";
      d.textContent = systemName ? "该系统暂无回放（先录制学习）" : "无技能";
      listEl.append(d);
      return;
    }
    for (const s of skills) {
      if (q && !`${s.name}`.toLowerCase().includes(q)) continue;
      const row = document.createElement("div");
      row.className = "sk" + (picked.some((p) => p.id === s.id) ? " on" : "");
      const nm = document.createElement("span");
      nm.className = "nm";
      nm.textContent = s.name;
      row.append(nm);
      if (s.requires_confirmation) {
        const w = document.createElement("span");
        w.className = "w"; w.textContent = "写";
        row.append(w);
      }
      const idx = picked.findIndex((p) => p.id === s.id);
      if (idx >= 0) {
        const o = document.createElement("span");
        o.className = "o"; o.textContent = String(idx + 1);
        row.append(o);
      }
      row.addEventListener("click", () => {
        const i = picked.findIndex((p) => p.id === s.id);
        if (i >= 0) picked.splice(i, 1); else picked.push(s);
        renderPicked();
        render();
      });
      // 单技能执行（popup 技能列表职能并入——行 hover 出执行钮，与组链并存）
      const one = document.createElement("button");
      one.className = "one";
      one.textContent = "执行";
      one.title = "单独执行该技能";
      one.addEventListener("click", (ev) => {
        ev.stopPropagation();
        // AH6 页内执行：SW attach 本页直接驱动（不再开扩展内部页——
        // 网页上下文 window.open 扩展页被 ERR_BLOCKED_BY_CLIENT 拦）
        void chrome.storage.local.remove("sl_exec_log");
        root.getElementById("pgl")!.textContent = "";
        // AH6b port 通道直达执行（去跳板：不再开执行页再点一次——面板
        // connect SW 长连接发请求，进度经 port 回流本面板）
        void execViaPort({ skillId: s.id });
      });
      row.append(one);
      listEl.append(row);
    }
  }

  let showAllSystems = false;  // 系统隔离默认开（仅本系统）；点系统头切换

  async function loadSkills(): Promise<void> {
    try {
      sysEl.textContent = sysEl.textContent + "·拉技能";
      const arr = await api("/executor/skills");
      // 系统隔离（用户裁定：打开 A 系统只应看到 A 的技能）——识别失败
      // （systemName 空）不得放行全部：显示空列表+明确提示，点系统头
      // 才显式看全部
      if (!showAllSystems && !systemName) {
        skills = [];
        listEl.replaceChildren();
        const d = document.createElement("div");
        d.className = "empty";
        d.textContent = "系统未识别（非业务页或未适配）——点上方系统名可查看全部";
        listEl.append(d);
        return;
      }
      skills = (Array.isArray(arr) ? arr : [])
        .filter((s) => showAllSystems || (s.system || "") === systemName);
      render();
    } catch (e: any) {
      listEl.replaceChildren();
      const d = document.createElement("div");
      d.className = "empty";
      d.textContent = `加载失败：${e?.message ?? e}`;
      listEl.append(d);
      sysEl.textContent = `技能加载失败（${String(e?.message || e).slice(0, 30)}）`;
    }
  }

  function payload(): { name: string; system: string; steps: Array<{ skill_id: number; overrides: Record<string, string> }> } | null {
    if (!picked.length) return null;
    return {
      name: cnEl.value.trim() || `链 ${new Date().toTimeString().slice(0, 5)}`,
      system: systemName || "通用",
      // AI2：面板编辑的 overrides（key 经 fill 候选防呆）随步保存
      steps: picked.map((p) => ({ skill_id: p.id,
                                  overrides: p.__ovr || {} })),
    };
  }

  async function api(path: string, init?: RequestInit): Promise<any> {
    let t = await token();
    let r = await Promise.race([
      fetch(`${AGENT}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${t}` },
      }),
      new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error("请求超时")), 15000)),
    ]);
    if (r.status === 401) {
      // 内部部署免登录：401 自动换 token 重试一次
      const tk = await autoSession();
      if (tk) {
        r = await Promise.race([
          fetch(`${AGENT}${path}`, {
            ...init,
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${tk}` },
          }),
          new Promise<never>((_, rej) =>
            setTimeout(() => rej(new Error("请求超时")), 15000)),
        ]);
      }
    }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  root.getElementById("sv")!.addEventListener("click", async () => {
    const p = payload();
    if (!p) return;
    try {
      await api("/chains", { method: "POST", body: JSON.stringify(p) });
      cnEl.value = ""; picked = [];
      renderPicked();
      render();
      await loadChains();
      note("链已保存", "ok");
    } catch (e: any) { note(`保存失败：${e.message}`, "err"); }
  });

  root.getElementById("go")!.addEventListener("click", async () => {
    const p = payload();
    if (!p) return;
    try {
      const r = await api("/chains", { method: "POST", body: JSON.stringify(p) });
      void chrome.storage.local.remove("sl_exec_log");
      root.getElementById("pgl")!.textContent = "";
      void execViaPort({ chainId: r.id });
    } catch (e: any) { note(`失败：${e.message}`, "err"); }
  });

  async function loadChains(): Promise<void> {
    try {
      const arr = await api(`/chains${systemName ? `?system=${encodeURIComponent(systemName)}` : ""}`);
      chsEl.replaceChildren();
      if (!Array.isArray(arr) || !arr.length) {
        const d = document.createElement("div");
        d.className = "empty"; d.textContent = "无";
        chsEl.append(d);
        return;
      }
      for (const c of arr) {
        const row = document.createElement("div");
        row.className = "ch";
        const nm = document.createElement("span");
        nm.className = "nm"; nm.textContent = c.name;
        const m = document.createElement("span");
        m.className = "m"; m.textContent = `${(c.steps || []).length} 步`;
        const run = document.createElement("button");
        run.className = "run"; run.textContent = "执行";
        run.addEventListener("click", () => {
          void chrome.storage.local.remove("sl_exec_log");
          void execViaPort({ chainId: c.id });
        });
        const del = document.createElement("button");
        del.className = "del"; del.textContent = "删";
        del.addEventListener("click", async () => {
          try { await api(`/chains/${c.id}`, { method: "DELETE" }); await loadChains(); }
          catch (e: any) { note(`删除失败：${e.message}`, "err"); }
        });
        row.append(nm, m, run, del);
        chsEl.append(row);
      }
    } catch (e: any) {
      chsEl.replaceChildren();
      const d = document.createElement("div");
      d.className = "empty";
      d.textContent = `链加载失败：${e.message}`;
      chsEl.append(d);
    }
  }

  qEl.addEventListener("input", () => render());

  // AI1 学习通知 + 待学消费：面板常驻页面（比 popup 生命周期可靠）——
  // 打开面板时消费待学会话，触发 learn.html 学习页
  void chrome.storage.local.get(["sl_last_learn", "sl_pending_learn"]).then((st) => {
    const r = (st as any).sl_last_learn;
    const p = (st as any).sl_pending_learn;
    if (r?.status === "done") note(`学习完成：${r.skillName ?? "新技能"}（技能 #${r.skillId}）`, "ok");
    else if (r?.status === "error") note(`上次自动学习失败：${r.error ?? ""}`, "err");
    if (p?.sid && Date.now() - p.at < 30 * 60 * 1000 && !r) {
      note("有待学习的录制——正在打开学习页…", "ok");
      chrome.storage.local.remove("sl_pending_learn");
      window.open(chrome.runtime.getURL(`learn.html?sid=${encodeURIComponent(p.sid)}`), "_blank");
    }
  }).catch(() => {});

  // 恢复历史执行进度（goto 导航销毁页面后，面板重开仍可见全程日志）
  void chrome.storage.local.get("sl_exec_log").then(({ sl_exec_log: log }) => {
    if (Array.isArray(log) && log.length) {
      const pg = root.getElementById("pg")!;
      const pgl = root.getElementById("pgl")!;
      pg.style.display = "block";
      pgl.textContent = log.join("\n");
      pgl.scrollTop = pgl.scrollHeight;
    }
  }).catch(() => {});

  // AH6 进度回流：SW 的 SL_PROGRESS 消息渲染到面板进度区（执行全程
  // 在本页可见——页内执行的核心反馈）
  chrome.runtime.onMessage.addListener((m: any) => {
    if (m?.type === "SL_PROGRESS") {
      const pg = root.getElementById("pg")!;
      const pgt = root.getElementById("pgt")!;
      const pgl = root.getElementById("pgl")!;
      pg.style.display = "block";
      if (String(m.msg).includes("链执行结束") || String(m.msg).includes("完成：")) {
        pgt.textContent = String(m.msg).includes("pass") ? "执行完成（通过）" : "执行结束";
        pgt.style.color = String(m.msg).includes("pass") ? "#16a34a" : "#dc2626";
      }
      pgl.textContent += `[${new Date().toTimeString().slice(0, 8)}] ${m.msg}
`;
      pgl.scrollTop = pgl.scrollHeight;
    }
  });

  // 录制状态徽标（只读展示——录制控制在 popup；面板提示防"录着忘了"）
  void chrome.storage.local.get("sl_recording").then(({ sl_recording: rec }) => {
    const dot = root.getElementById("recdot")!;
    if (rec) {
      dot.classList.add("on");
      dot.title = "录制中（控制见插件弹窗）";
    }
  }).catch(() => {});

  void detectSystem().then(loadSkills).then(loadChains);
}

// 懒挂载：常驻注入（manifest CS）但只显示一个小徽标（低干扰）——点徽标
// 或收到 skilllens:show-space 事件才展开完整面板。popup 注入链在 CDP
// 托管浏览器下不可靠（executeScript 与 popup 卸载竞态，多轮实锤），
// 徽标自唤起是零依赖路径。
window.addEventListener("skilllens:show-space", () => {
  try { mount(); } catch (e) { console.warn("[SL] mount fail:", e); }
});
// P0 排障：badge click 的 mount 错误也要浮出（幂等守卫抛错除外）
window.addEventListener("error", (e) => {
  console.warn("[SL] panel error:", e.message);
});

mountBadge();

function mountBadge(): void {
  if (document.getElementById("skilllens-badge-host")) return;
  const host = document.createElement("div");
  host.id = "skilllens-badge-host";
  host.setAttribute("data-skilllens-ui", "badge");
  host.style.cssText = "position:fixed; bottom:20px; right:20px; z-index:2147483647;";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      .b {
        width:36px; height:36px; border-radius:50%; border:none; cursor:pointer;
        background:linear-gradient(135deg,#2563eb,#7c3aed); color:#fff;
        font:700 12px/36px -apple-system,"Segoe UI",system-ui,sans-serif;
        box-shadow:0 4px 14px rgba(37,99,235,.4); text-align:center;
      }
      .b:hover { transform:scale(1.08); }
    </style>
    <button class="b" title="SkillLens 空间">SL</button>
  `;
  root.querySelector("button")!.addEventListener("click", () => {
    try { mount(); } catch (e) { console.warn("[SL] badge mount:", e); }
  });
  document.documentElement.appendChild(host);
}
