"""AF3 例程库：目标系统怪癖的收编地（设计原则①——基座越接越强）。

全部从 S43-4 已验证代码移植（出处标注）。新增怪癖一律先在 s43 类脚本里
真机验证过，再收编进来。
"""
from playwright.async_api import Page


async def run_routine(page: Page, name: str) -> None:
    fn = _ROUTINES.get(name)
    if fn is None:
        raise ValueError(f"未知例程: {name}（可用: {sorted(_ROUTINES)}）")
    await fn(page)


async def close_guide(page: Page) -> None:
    """禅道新手引导弹窗（s43_zentao_qa.py close_guide）。"""
    try:
        await page.get_by_text("我知道了").click(timeout=2000)
        await page.wait_for_timeout(800)
    except Exception:
        pass


async def confirm_el_box(page: Page) -> None:
    """element-plus 全局确认框（s43_ruoyi_perm.py _confirm_logout_box——
    .el-message-box__btns 定位实测层级最稳）。"""
    await page.wait_for_timeout(800)
    try:
        for _ in range(3):
            btn = page.locator(".el-message-box__btns button").filter(has_text="确定")
            if await btn.count() and await btn.first.is_visible():
                await btn.first.click(timeout=4000)
                await page.wait_for_timeout(1500)
                return
            await page.wait_for_timeout(600)
    except Exception:
        pass


async def biz_frame_submit(page: Page) -> None:
    """禅道 iframe 业务页提交（s43_zentao_qa.py submit_form——submit 控件
    按类型优先+文本兜底）。"""
    f = page
    for fr in page.frames:
        if fr is not page.main_frame:
            f = fr
            break
    try:
        btn = f.locator("button[type=submit], #submit").first
        if await btn.count() == 0:
            btn = f.locator("button", has_text="保存").last
        await btn.click(timeout=8000)
        await page.wait_for_timeout(4000)
    except Exception:
        pass


async def select2_pick(page: Page, selector_arg: str = "") -> None:
    """select2 AJAX 下拉（lesson #22：开容器→填搜索框→点结果——永不直填
    hidden input）。selector_arg 暂未用（flow 解释器 AF4 传参形态扩展）。"""
    container = page.locator(".select2-container").first
    await container.click()
    await page.wait_for_timeout(600)
    search = page.locator(".select2-search__field").first
    await search.fill(selector_arg)
    await page.wait_for_timeout(800)
    await page.locator(".select2-results__option").first.click()
    await page.wait_for_timeout(800)


async def el_select_pick(page: Page, selector_arg: str = "") -> None:
    """element-plus el-select（lesson #27：空态是 .el-select__placeholder 容器
    裸 span）。selector_arg=要选的选项文本。"""
    await page.locator(".el-select").first.click()
    await page.wait_for_timeout(800)
    opt = page.locator(".el-select-dropdown__item").filter(has_text=selector_arg).first
    await opt.click(timeout=8000)
    await page.wait_for_timeout(500)


_ROUTINES = {
    "close_guide": close_guide,
    "confirm_el_box": confirm_el_box,
    "biz_frame_submit": biz_frame_submit,
    "select2_pick": select2_pick,
    "el_select_pick": el_select_pick,
}
