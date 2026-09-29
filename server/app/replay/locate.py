from playwright.async_api import Locator, Page


async def locate(page: Page, label: str) -> tuple[Locator, str]:
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
    ]
    for locator, strategy in candidates:
        # 只吞定位查询异常（count/is_visible）；click/fill 在 runner 中执行，异常正常上抛
        try:
            count = await locator.count()
        except Exception:
            continue
        if count > 0:
            try:
                visible = await locator.first.is_visible()
            except Exception:
                continue
            if visible:
                return locator.first, strategy
    raise LookupError(f"semantic locate failed: {label!r}")
