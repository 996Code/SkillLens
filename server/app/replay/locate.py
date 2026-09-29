from playwright.async_api import Locator, Page


async def _try_locate(page: Page, label: str,
                      prefer_controls: bool = False) -> tuple[Locator, str] | None:
    candidates: list[tuple[Locator, str]] = [
        (page.get_by_role("button", name=label), "role-button"),
        (page.get_by_text(label, exact=True), "text"),
        (page.get_by_placeholder(label), "placeholder"),
        (page.get_by_label(label), "label"),
        # 框架自动生成 id（antd rc_select_N 等）回退：采集侧 input-key 链可能
        # 抓到这类 id（元素无 placeholder/aria 时）——回放时按 id 兜底定位
        (page.locator(f"#{label}"), "id"),
        # S35：无可访问名图标按钮的 name 属性兜底（采集侧 nameAttr 兜底链）
        (page.locator(f'[name="{label}"]'), "name-attr"),
        # S36：Frappe（ERPNext）模态输入框的 data-fieldname 兜底。
        # 控件优先：字段包装 div 同带 data-fieldname 且 DOM 序在前，
        # fill 会命中不可填元素——先试 input/textarea/select 再试任意元素
        (page.locator(
            f'input[data-fieldname="{label}"], textarea[data-fieldname="{label}"], '
            f'select[data-fieldname="{label}"]'), "data-fieldname"),
        (page.locator(f'[data-fieldname="{label}"]'), "data-fieldname-any"),
        # S35：input[type=submit] 的 value 兜底（采集侧 inputValue 链）
        (page.locator(f'input[value="{label}"]'), "input-value"),
    ]
    if prefer_controls:
        # S36：fill 场景控件优先——Frappe 把字段名渲染成可见帮助文本，
        # text/role 策略会抢先命中文本节点（不可填），控件类策略前置
        order = ["placeholder", "label", "name-attr", "data-fieldname",
                 "id", "data-fieldname-any", "input-value",
                 "role-button", "text"]
        by_strategy = {s: (l, s) for l, s in candidates}
        candidates = [by_strategy[s] for s in order if s in by_strategy]
    for locator, strategy in candidates:
        # 只吞定位查询异常（count/is_visible）；click/fill 在 runner 中执行，异常正常上抛
        try:
            count = await locator.count()
        except Exception:
            continue
        if count > 0:
            # S36：遍历可见匹配；多个可见时优先开放模态内的——
            # ERPNext 列表"存过滤器"的 Save 与模态 Save 同名同可见，
            # 用户交互上下文在顶层容器（模态），这是通用 UI 原则非框架适配
            visible_idx = []
            for i in range(min(count, 10)):
                try:
                    if await locator.nth(i).is_visible():
                        visible_idx.append(i)
                except Exception:
                    continue
            if not visible_idx:
                continue
            if len(visible_idx) > 1:
                in_modal = await _first_in_open_modal(page, locator, visible_idx)
                if in_modal is not None:
                    return locator.nth(in_modal), strategy
            return locator.nth(visible_idx[0]), strategy
    return None


async def _first_in_open_modal(page: Page, locator: Locator,
                               idx: list[int]) -> int | None:
    """多个可见匹配中，返回位于开放模态/对话框内的第一个下标（无则 None）。"""
    has_modal = await page.locator(
        ".modal.show, [role='dialog'][aria-modal='true'], [aria-modal='true']"
    ).count()
    if not has_modal:
        return None
    for i in idx:
        try:
            if await locator.nth(i).evaluate(
                "el => !!(el.closest('.modal.show, [role=dialog], [aria-modal=true]'))"
            ):
                return i
        except Exception:
            continue
    return None


async def locate(page: Page, label: str, *,
                 labels: list[str] | None = None,
                 tag: str | None = None,
                 ordinal: int | None = None,
                 path: str | None = None,
                 prefer_controls: bool = False) -> tuple[Locator, str]:
    """S36 多信号定位：快路径逐候选 label 走全策略矩阵（任何 UI 框架
    只要暴露任一信号即可命中，无需逐框架适配）；全部失败后结构兜底
    （path 祖先链 + ordinal nth-of-type，唯一命中才用——宁缺毋滥）。"""
    for lbl in [label, *(labels or [])]:
        if not lbl:
            continue
        hit = await _try_locate(page, lbl, prefer_controls=prefer_controls)
        if hit is not None:
            return hit
    if path:
        segs = [s for s in path.split(">") if s]
        if segs:
            last = segs[-1]
            sel = " ".join(segs) if len(segs) == 1 else f"{' '.join(segs[:-1])} {last}"
            if ordinal and ordinal > 1:
                sel += f":nth-of-type({ordinal})"
            locator = page.locator(sel)
            try:
                count = await locator.count()
                if count == 1 and await locator.first.is_visible():
                    return locator.first, "structural"
            except Exception:
                pass
    raise LookupError(f"semantic locate failed: {label!r}")
