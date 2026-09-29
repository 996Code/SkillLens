export interface ElementDesc {
  tag: string;
  role: string;
  label: string;
  text: string;
  path: string;
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

export function describeElement(el: Element): ElementDesc {
  const target = resolveActionable(el);
  const tag = target.tagName.toLowerCase();
  const role = target.getAttribute("role") ?? implicitRole(target);
  const text = (target.textContent ?? "").trim().slice(0, 100);
  const label = target.getAttribute("aria-label")
    ?? target.getAttribute("placeholder")
    ?? target.getAttribute("title")
    ?? inputValue(target)
    ?? (text !== "" ? text : undefined)
    ?? nameAttr(target);
  return { tag, role, label, text, path: domPath(target) };
}

/** S35：无任何可访问名的图标按钮（Dolibarr 搜索键 name="button_search_x"）
 * ——name 属性兜底（机器名但稳定可定位）。 */
function nameAttr(el: Element): string | undefined {
  const v = el.getAttribute("name");
  return v && v.trim() !== "" ? v.trim().slice(0, 100) : undefined;
}

/** S35：input[type=submit/button] 的 value 是唯一人读标签
 * （Dolibarr 等经典表单的提交按钮无文本只有 value）。 */
function inputValue(el: Element): string | undefined {
  if (!(el instanceof HTMLInputElement)) return undefined;
  const v = el.value;
  return typeof v === "string" && v.trim() !== "" ? v.trim().slice(0, 100) : undefined;
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
