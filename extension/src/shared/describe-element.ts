import { SENSITIVE_KEY_RE } from "./redact";

export interface ElementDesc {
  tag: string;
  role: string;
  label: string;
  text: string;
  path: string;
  /** S36 多信号：全部可用定位信号（按优先序）。回放侧逐个尝试——
   * 任何 UI 框架只要暴露其中任一信号即可定位，无需逐框架适配。 */
  labels: string[];
  /** 同类兄弟中的序号（结构兜底信号：纯 div 布局无任何属性时
   * 用 tag+ordinal nth-of-type 定位）。 */
  ordinal: number;
}

const ACTIONABLE = ["button", "a", "input", "select", "textarea"];

/** S42-10（借鉴 Browser-Use 的 CDP 事件监听检测）：content script 无 CDP，
 * 用 computed cursor:pointer + tabindex 近似"实际可交互"信号——
 * 自绘控件（zui picker 等绑 click 的 div）无语义标签但可点击。
 * 注意 cursor 可继承：子元素继承 pointer 不算——只有"自己声明
 * pointer 而父级不是"才是控件本体（否则会停在内部 span 上）。 */
function looksInteractive(el: Element): boolean {
  if (el.getAttribute("tabindex") && el.getAttribute("tabindex") !== "-1") return true;
  try {
    const own = getComputedStyle(el).cursor;
    if (own === "pointer") {
      const parent = el.parentElement;
      const parentCursor = parent ? getComputedStyle(parent).cursor : "";
      return parentCursor !== "pointer";
    }
  } catch {
    /* detached 元素 */
  }
  return false;
}

/** S34：图标按钮泛化——点击命中的常是内部 <i>/<svg> 图标（Odoo 等
 * 框架的 Save/Edit 按钮无文本只有图标），上溯到最近可操作祖先取其
 * aria-label/text；3 层内无可操作祖先则保持原元素（避免过度上溯）。 */
function resolveActionable(el: Element): Element {
  let cur: Element | null = el;
  for (let i = 0; cur && i < 3; i++) {
    const tag = cur.tagName.toLowerCase();
    if (ACTIONABLE.includes(tag) || cur.getAttribute("role") === "button"
        || looksInteractive(cur)) {
      return cur;
    }
    cur = cur.parentElement;
  }
  return el;
}

function clean(v: string | null | undefined): string | undefined {
  if (typeof v !== "string") return undefined;
  const t = v.trim().slice(0, 100);
  return t !== "" ? t : undefined;
}

/** S36 多信号采集：一次性收集元素的全部定位信号（去重、按优先序）。
 * label = labels[0]（骨架签名兼容）；回放侧消费整个数组。 */
function collectLabels(el: Element): string[] {
  const candidates = [
    el.getAttribute("aria-label"),
    el.getAttribute("placeholder"),
    el.getAttribute("title"),
    inputValue(el),
    textSignal(el),
    el.getAttribute("data-fieldname"),
    el.getAttribute("name"),
    // S42-9 根治：稳定信号（表单组字段标签）排在自动 id 之前——
    // 自绘控件（zui picker）的自动 id（pick-_pick101）跨会话不稳定，
    // 排前面会让骨架签名漂移（LCS 丢步）且回放先试必败的 id。
    // 字段标签（"解决方案"）跨会话稳定，是 picker 的首选语义。
    formGroupLabel(el),
    // S43-4：select2 渲染层取相邻原生 select 的 name（Snipe-IT 等
    // bootstrap 系——渲染层 placeholder 回放不可定位）
    select2HostSelect(el),
    el.id && !isFrameworkId(el.id) ? el.id : undefined,
  ];
  const out: string[] = [];
  for (const c of candidates) {
    const v = clean(c);
    if (v && !out.includes(v)) out.push(v);
  }
  return out;
}

/** 文本信号：CSS 内容（<style> 或样式文本）不是人读标签，过滤。 */
function textSignal(el: Element): string | undefined {
  if (el.tagName === "STYLE") return undefined;
  const t = (el.textContent ?? "").trim().slice(0, 100);
  if (!t) return undefined;
  // CSS 片段特征（禅道实测：上溯到容器时 textContent 是整段样式表）
  if (/^[:\w-]+\s*\{|^@media|^--[\w-]+:/.test(t)) return undefined;
  // S42-10：纯数字短文本是控件计数徽章（picker "0"）——不是人读标签
  if (/^\d{1,2}$/.test(t)) return undefined;
  return t;
}

/** S43-4：select2 渲染层的相邻原生 select（结构铁律：select2 容器
 * 紧邻被隐藏的原生 select）。渲染层自身无语义（placeholder 如
 * "Select Status" 回放不可定位），相邻 select 的 name 是稳定锚点。 */
function select2HostSelect(el: Element): string | undefined {
  const container = el.classList?.contains("select2-container")
    ? el
    : el.closest(".select2-container");
  if (!container) return undefined;
  let cur: Element | null = container;
  for (let i = 0; i < 3 && cur; i++) {
    const prev = cur.previousElementSibling;
    if (prev?.tagName === "SELECT" && prev.getAttribute("name")) {
      return prev.getAttribute("name") ?? undefined;
    }
    cur = prev;
  }
  return undefined;
}

/** 最近表单组的字段标签（zui/ant/element 表单布局通用）。
 * 注意用精确 class token（.form-group）——子串匹配会先命中
 * picker 的 form-group-wrapper（label 是 wrapper 的兄弟节点）。 */
function formGroupLabel(el: Element): string | undefined {
  const fg = el.closest(".form-group, .ant-form-item, [class*=form-item], [class*=field]");
  if (!fg) return undefined;
  const label = fg.querySelector("[class*=label]:not([class*=label-]), label, [class*=title]");
  if (!label) return undefined;
  // S42-9：label 内的操作链接（"所有"/"清空"）不是字段名——剔除后取纯文本
  // S42-12：嵌套控件同样剔除——禅道 form-label 内嵌 checkbox 快捷项
  // （<label>所有</label>）与 input 值会把字段名污染成"影响版本所有"，
  // 该值随选中状态漂移，是跨会话不稳定信号（回放 has_text 必失配）
  const clone = label.cloneNode(true) as Element;
  clone.querySelectorAll(
    "a, button, label, input, select, textarea, " +
    "[class*=link], [class*=action], [class*=checkbox], [class*=radio], [class*=picker], [class*=control]",
  ).forEach((n) => n.remove());
  const t = (clone.textContent ?? "").trim().slice(0, 50);
  return t || undefined;
}

export function describeElement(el: Element): ElementDesc {
  const target = resolveActionable(el);
  const tag = target.tagName.toLowerCase();
  const role = target.getAttribute("role") ?? implicitRole(target);
  const text = clean(target.textContent) ?? "";
  const labels = collectLabels(target);
  return {
    tag, role, label: labels[0] ?? "", text,
    path: domPath(target), labels, ordinal: ordinalAmongSiblings(target),
  };
}

/** 结构信号：同类兄弟中的序号（1-based）。 */
function ordinalAmongSiblings(el: Element): number {
  const parent = el.parentElement;
  if (!parent) return 1;
  let n = 0;
  let me = 0;
  for (const c of Array.from(parent.children)) {
    if (c.tagName === el.tagName) {
      n += 1;
      if (c === el) me = n;
    }
  }
  return me || 1;
}

// 框架自动生成 id 跨会话不稳定（antd 每次重新编号），不能当定位信号
const FRAMEWORK_ID_RE = /^(rc_|ant-|ant_|__|mui-|:r\d|radix-|:v-|el-id-|pick-_pick)/;

function isFrameworkId(id: string): boolean {
  return FRAMEWORK_ID_RE.test(id) || /^\d+$/.test(id);
}

/** S35：input[type=submit/button] 的 value 是唯一人读标签
 * （Dolibarr 等经典表单的提交按钮无文本只有 value）。
 * S42 安全红线：密码框与敏感命名字段的 value 不得进 labels——
 * 否则明文经定位信号通道绕过 capture 层脱敏直接落库。 */
function inputValue(el: Element): string | undefined {
  if (!(el instanceof HTMLInputElement)) return undefined;
  if (el.type === "password") return undefined;
  if ((el.getAttribute("autocomplete") ?? "").toLowerCase().includes("password")) return undefined;
  const identity = `${el.name ?? ""} ${el.id ?? ""}`;
  if (SENSITIVE_KEY_RE.test(identity)) return undefined;
  return clean(el.value);
}

function implicitRole(el: Element): string {
  const tag = el.tagName.toLowerCase();
  if (["button", "a", "input", "select", "textarea"].includes(tag)) return tag;
  return "";
}

function domPath(el: Element): string {
  const parts: string[] = [];
  let cur: Element | null = el;
  while (cur && cur.parentElement && parts.length < 5) {
    parts.unshift(cur.tagName.toLowerCase());
    cur = cur.parentElement;
  }
  return parts.join(">");
}
