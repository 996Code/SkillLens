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
    ?? text;
  return { tag, role, label, text, path: domPath(target) };
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
