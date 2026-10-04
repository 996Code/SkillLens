"""AG2 resolver 编译器：locate 策略矩阵 → 插件端可执行候选序列。

瘦执行器架构（协议 §2 resolve 指令）：服务端编译有序候选 selector +
resolver JS 脚本，插件 Runtime.evaluate 按序实测（可见+可点+非导航容器
谓词），首个命中返回 rect——判定语义与 locate.py 策略矩阵对齐（语义强度
序同源；命中与否由确定性实测决定，LLM 不参与）。
"""
from app.replay.locate import _xpath_str

_NAV_EXCLUDE_XPATH = (
    'not(ancestor-or-self::*[contains(@class, "sidebar") or '
    'contains(@class, "navbar") or contains(@class, "nav-link")])'
)


def _candidate(strategy: str, selector: str, kind: str = "click",
               anchor: str | None = None) -> dict:
    out = {"strategy": strategy, "selector": selector, "kind": kind}
    if anchor:
        out["anchor"] = anchor
    return out


def compile_resolve_candidates(label: str, labels: list[str] | None = None,
                               tag: str | None = None,
                               ordinal: int | None = None,
                               path: str | None = None,
                               row_anchor: str | None = None) -> list[dict]:
    """locate 策略矩阵的编译版：语义强度序产候选 selector。

    与 locate() 的对应关系（策略名同源便于审计）：
    title-attr（强语义，排导航）→ aria-attr（图标按钮无文本）→
    role-button 精确 → form-group 控件（>3 字符）→ select2-by-name →
    menuitem → text（排 tooltip/导航）→ placeholder 精确 →
    el-select 容器 → label → id → name-attr →
    row-anchor（AG5：行操作触发器——宿主行文本过滤，labels/row_anchor）。
    """
    # short_label 门：防 'on' 等短值子串误命中——但 JeecG "*表名"（3 字符
    # 含 ASCII 星号+中文）是真实字段名——放宽为：纯 ASCII ≤3 才跳过
    short_label = len(label) <= 3 and all(c.isascii() for c in label)
    cands: list[dict] = [
        _candidate("title-attr",
                   f'//*[@title={_xpath_str(label)} and {_NAV_EXCLUDE_XPATH}]'),
        # AG5：图标按钮文本空、标识在 aria-label（Odoo o_form_button_save
        # 实证："Save manually" 无文本）——强语义，紧跟 title
        _candidate("aria-attr", f'[aria-label="{label}"]'),
        _candidate("role-button", f'[role="button"]', kind="role"),
    ]
    if not short_label:
        cands += [
            _candidate("form-group-control",
                       '.form-group, .ant-form-item', kind="form-group-control"),
            _candidate("form-group-native",
                       '.form-group, .ant-form-item', kind="form-group-native"),
            _candidate("select2-by-name",
                       f'select[name="{label}"] ~ .select2-container'),
        ]
    cands += [
        _candidate("menuitem",
                   f'//*[@role="menuitem" or @role="option" or @role="menu"]'
                   f'[normalize-space(.)={_xpath_str(label)}]'),
        # AG5：ant-dropdown 菜单项挂 body（hover 态渲染）——CSS 版 menuitem
        # 供插件端 querySelectorAll（XPath 形态插件端不执行）
        _candidate("menuitem-css", '[role="menuitem"], .ant-dropdown-menu-item, li[role="option"]',
                   kind="menuitem-text"),
        _candidate("text",
                   f'//*[normalize-space(text())={_xpath_str(label)} and '
                   f'not(ancestor-or-self::*[contains(@class,"tooltip") or '
                   f'@aria-hidden="true" or contains(@class,"sidebar") or '
                   f'contains(@class,"navbar") or '
                   f'contains(@class,"nav-link")])]'),
        # placeholder 两义性（列表搜索框 vs 模态表单——JeecG "请输入表名"
        # 实证同页两处）：容器内优先（模态/抽屉/表单组）
        _candidate("placeholder-modal",
                   '.ant-modal-content input, .ant-drawer-content input, '
                   '.el-dialog input, [role=dialog] input', kind="placeholder-modal"),
        _candidate("placeholder", f'[placeholder="{label}"]', kind="fill"),
        # Frappe/ERPNext（官方 cypress fill_field 模式）：input 无 name/
        # placeholder——选择器是 [data-fieldname=X] input（容器+后代）
        _candidate("data-fieldname", f'[data-fieldname="{label}"] input', kind="fill"),
        # Frappe save（官方 cypress save 命令）：button[data-label=Save]
        # （data-label 属性非文本）
        _candidate("frappe-save", 'button[data-label="Save"], .primary-action', kind="frappe-save"),
        _candidate("el-select-placeholder", '.el-select', kind="el-select"),
        _candidate("label", "label", kind="label"),
        _candidate("id", f'#{label}'),
        _candidate("name-attr", f'[name="{label}"]'),
    ]
    # AG5 row-anchor：行操作触发器（JeecG"更多"下拉等）——触发词在含
    # 宿主行文本的行内点击（kind=row-trigger 由插件端行内找 label）
    if row_anchor:
        import re as _re
        toks = _re.findall(r"[A-Za-z0-9_]{4,}", row_anchor)
        if toks:
            cands.append(_candidate(
                "row-anchor", ".ant-table-row, .list-item, .grid-row, tr",
                kind="row-trigger", anchor=toks[0]))
    return cands


_RESOLVER_JS_TEMPLATE = """(args) => {
  const candidates = args.candidates;
  const label = args.label;
  if (!candidates.length) return {hit: false, reason: "MISS"};
  const visible = (el) => {
    if (!el.isConnected) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.offsetParent !== null;
  };
  const navExcluded = (el) => !el.closest(
    '.sidebar, .nav, .menu, [class*=sidebar], [class*=navbar], [class*=nav-link]');
  const findByStrategy = (c) => {
    const doc = document;
    switch (c.kind) {
      case "role": {
        // 语义与 locate 的 get_by_role(exact=True) 对齐——不加 nav 排除
        // （locate 七系统验证行为：nav 冲突由 title 强语义先行解决）
        const els = [...doc.querySelectorAll('[role="button"], button')];
        const hit = els.find(el => visible(el) &&
          (el.textContent || '').trim() === label);
        return hit || null;
      }
      case "form-group-control": {
        const groups = [...doc.querySelectorAll(c.selector)].filter(
          g => (g.textContent || '').includes(label));
        for (const g of groups) {
          const ctl = g.querySelector(
            '.select2-container, .picker, .ant-select, .ant-picker');
          if (ctl && visible(ctl)) return ctl;
        }
        return null;
      }
      case "form-group-native": {
        const groups = [...doc.querySelectorAll(c.selector)].filter(
          g => (g.textContent || '').includes(label));
        for (const g of groups) {
          const ctl = g.querySelector('input, select, textarea');
          if (ctl && visible(ctl)) return ctl;
        }
        return null;
      }
      case "el-select": {
        const els = [...doc.querySelectorAll('.el-select:has(.el-select__placeholder), .el-select')];
        return els.find(el => visible(el) &&
          (el.textContent || '').includes(label)) || null;
      }
      case "label": {
        const els = [...doc.querySelectorAll('label')];
        return els.find(el => visible(el) &&
          (el.textContent || '').trim() === label) || null;
      }
      default: {
        const els = [...doc.querySelectorAll(c.selector)];
        return els.find(el => visible(el) && navExcluded(el)) ||
               (els.length === 1 ? els[0] : null);
      }
    }
  };
  for (let i = 0; i < candidates.length; i++) {
    let el = null;
    try { el = findByStrategy(candidates[i]); } catch (e) { continue; }
    if (!el) continue;
    const r = el.getBoundingClientRect();
    return {hit: true, index: i, strategy: candidates[i].strategy,
            rect: {x: r.x, y: r.y, width: r.width, height: r.height},
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            disabled: !!el.disabled};
  }
  return {hit: false, reason: "no-candidate-visible"};
}"""


def build_resolver_js(candidates: list[dict]) -> str:
    """自包含 resolver 脚本（插件 Runtime.evaluate 直接执行）。

    无候选 → 显式 MISS（协议：触发服务端当轮 LLM 介入）。
    """
    if not candidates:
        return "(args) => ({hit: false, reason: 'MISS'})"
    return _RESOLVER_JS_TEMPLATE
