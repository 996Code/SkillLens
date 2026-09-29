// 框架自动生成的 id 跨会话不稳定（antd 每次重新编号），不能当语义键——
// 块 P 实测：新浪 rc_select_0 录制可用但语义失真。跳过后继续回退链。
const FRAMEWORK_ID_RE = /^(rc_|ant-|ant_|__|mui-|:r\d|radix-|:v-)/;

function isFrameworkId(id: string): boolean {
  return FRAMEWORK_ID_RE.test(id) || /^\d+$/.test(id);
}

export function inputKey(el: HTMLInputElement | HTMLTextAreaElement): string | null {
  const name = el.name || null;
  const id = el.id && !isFrameworkId(el.id) ? el.id : null;
  // S36：Frappe（ERPNext）模态输入框只有 data-fieldname——语义键兜底
  return name || id || el.getAttribute("placeholder") || el.getAttribute("aria-label")
    || el.getAttribute("data-fieldname") || null;
}
