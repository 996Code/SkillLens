export function inputKey(el: HTMLInputElement | HTMLTextAreaElement): string | null {
  return el.name || el.id || el.getAttribute("placeholder") || el.getAttribute("aria-label") || null;
}
