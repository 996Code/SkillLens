export interface ElementDesc {
  tag: string;
  role: string;
  label: string;
  text: string;
  path: string;
}

export function describeElement(el: Element): ElementDesc {
  const tag = el.tagName.toLowerCase();
  const role = el.getAttribute("role") ?? implicitRole(el);
  const text = (el.textContent ?? "").trim().slice(0, 100);
  const label = el.getAttribute("aria-label")
    ?? el.getAttribute("placeholder")
    ?? el.getAttribute("title")
    ?? text;
  return { tag, role, label, text, path: domPath(el) };
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
