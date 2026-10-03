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


def _candidate(strategy: str, selector: str, kind: str = "click") -> dict:
    return {"strategy": strategy, "selector": selector, "kind": kind}


def compile_resolve_candidates(label: str, labels: list[str] | None = None,
                               tag: str | None = None,
                               ordinal: int | None = None,
                               path: str | None = None) -> list[dict]:
    """locate 策略矩阵的编译版：语义强度序产候选 selector。

    与 locate() 的对应关系（策略名同源便于审计）：
    title-attr（强语义，排导航）→ role-button 精确 → form-group 控件
    （>3 字符）→ select2-by-name → menuitem → text（排 tooltip/导航）
    → placeholder 精确 → el-select 容器 → label → id → name-attr。
    """
    short_label = len(label) <= 3
    cands: list[dict] = [
        _candidate("title-attr",
                   f'//*[@title={_xpath_str(label)} and {_NAV_EXCLUDE_XPATH}]'),
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
        _candidate("text",
                   f'//*[normalize-space(text())={_xpath_str(label)} and '
                   f'not(ancestor-or-self::*[contains(@class,"tooltip") or '
                   f'@aria-hidden="true" or contains(@class,"sidebar") or '
                   f'contains(@class,"navbar") or '
                   f'contains(@class,"nav-link")])]'),
        _candidate("placeholder", f'[placeholder="{label}"]', kind="fill"),
        _candidate("el-select-placeholder", '.el-select', kind="el-select"),
        _candidate("label", "label", kind="label"),
        _candidate("id", f'#{label}'),
        _candidate("name-attr", f'[name="{label}"]'),
    ]
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
