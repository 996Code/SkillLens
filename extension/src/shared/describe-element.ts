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

/** S34：图标按钮泛化——点击命中的常是内部 <i>/<svg> 图标（Odoo 等
 * 框架的 Save/Edit 按钮无文本只有图标），上溯到最近可操作祖先取其
 * aria-label/text；3 层内无可操作祖先则保持原元素（避免过度上溯）。 */
function resolveActionable(el: Element): Element {
  let cur: Element | null = el;
  for (let i = 0; cur && i < 3; i++) {
    const tag = cur.tagName.toLowerCase();
    if (ACTIONABLE.includes(tag) || cur.getAttribute("role") === "button") {
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
    (el.textContent ?? "").trim().slice(0, 100) || undefined,
    el.getAttribute("data-fieldname"),
    el.getAttribute("name"),
    el.id && !isFrameworkId(el.id) ? el.id : undefined,
  ];
  const out: string[] = [];
  for (const c of candidates) {
    const v = clean(c);
    if (v && !out.includes(v)) out.push(v);
  }
  return out;
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
const FRAMEWORK_ID_RE = /^(rc_|ant-|ant_|__|mui-|:r\d|radix-|:v-)/;

function isFrameworkId(id: string): boolean {
  return FRAMEWORK_ID_RE.test(id) || /^\d+$/.test(id);
}

/** S35：input[type=submit/button] 的 value 是唯一人读标签
 * （Dolibarr 等经典表单的提交按钮无文本只有 value）。 */
function inputValue(el: Element): string | undefined {
  if (!(el instanceof HTMLInputElement)) return undefined;
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
