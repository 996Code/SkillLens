// 框架自动生成的 id 跨会话不稳定（antd 每次重新编号），不能当语义键——
// 块 P 实测：新浪 rc_select_0 录制可用但语义失真。跳过后继续回退链。
// S42：Element Plus 的 el-id-XXXX-N 同类（若依实测：两轮录制 id 不同，
// input 键对不上 → 变量归纳失败 → 骨架丢 fill 步骤）。
const FRAMEWORK_ID_RE = /^(rc_|ant-|ant_|__|mui-|:r\d|radix-|:v-|el-id-)/;

function isFrameworkId(id: string): boolean {
  return FRAMEWORK_ID_RE.test(id) || /^\d+$/.test(id);
}

export function inputKey(el: HTMLInputElement | HTMLTextAreaElement): string | null {
  const name = el.name || null;
  const id = el.id && !isFrameworkId(el.id) ? el.id : null;
  // S36：Frappe（ERPNext）模态输入框只有 data-fieldname——语义键兜底
  // S43-4：select2 弹层搜索输入无任何属性——取宿主 hidden select 的
  // name（select2 实测：搜索字段动态创建，三回退全空则整步丢失）
  return name || id || el.getAttribute("placeholder") || el.getAttribute("aria-label")
    || el.getAttribute("data-fieldname") || select2HostName(el) || null;
}

/** select2 弹层输入的宿主 select name——弹层 DOM 挂在容器尾部或
 * body 下的 .select2-dropdown，宿主 select 在弹层挂载点之前的
 * .select2-container 兄弟链上。 */
function select2HostName(el: Element): string | null {
  if (!(el instanceof HTMLInputElement)) return null;
  if (!el.classList.contains("select2-search__field")) return null;
  // 弹层可能挂在容器内或 body 下（select2 open 时 dropdown 移入
  // .select2-container）；向上找容器，再从容器向前找 hidden select
  let container = el.closest(".select2-container");
  if (!container) return null;
  // 容器在表单内：前邻链上的 hidden select
  let cur: Element | null = container;
  for (let i = 0; i < 3 && cur; i++) {
    const prev = cur.previousElementSibling;
    if (prev?.tagName === "SELECT") {
      return prev.getAttribute("name");
    }
    cur = prev;
  }
  // Snipe-IT（老版 select2）：搜索字段在 body 下动态弹层容器里（与
  // 宿主无 DOM/aria 关联）。铁律：select2 打开时**原容器**也带
  // --open 类且在表单内、前邻即 hidden select——按此反查宿主
  const doc = el.ownerDocument;
  for (const c of Array.from(doc.querySelectorAll(".select2-container--open"))) {
    const prev = c.previousElementSibling;
    if (prev?.tagName === "SELECT" && prev.getAttribute("name")) {
      return prev.getAttribute("name");
    }
  }
  return null;
}
