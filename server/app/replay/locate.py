from playwright.async_api import Locator, Page


async def _try_locate(page: Page, label: str,
                      prefer_controls: bool = False) -> tuple[Locator, str] | None:
    # S42：iframe 架构应用（禅道综合界面等）业务内容渲染在子 frame——
    # 逐 frame 尝试候选策略（主 frame 优先）
    frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    for frame in frames:
        hit = await _try_locate_in_frame(page, frame, label, prefer_controls)
        if hit is not None:
            return hit
    return None


async def _try_locate_in_frame(page: Page, frame, label: str,
                               prefer_controls: bool) -> tuple[Locator, str] | None:
    candidates: list[tuple[Locator, str]] = [
        # S42-12：精确名优先——get_by_role(name=) 默认子串匹配，禅道 Bug
        # 表单的"保存模板"会抢在真提交按钮"保存"之前命中（点击只触发
        # 模板面板不开提交）。子串匹配降级为最后兜底。
        (frame.get_by_role("button", name=label, exact=True), "role-button"),
        # S42-8：自定义控件（zui picker 等）——label 文本命中的是 <label>
        # 元素（点击 label 不开下拉），正确语义是"含该 label 的表单组
        # 内的控件"（picker/select/input）。
        # S42-9：:has(label:text-is()) 组合实测不生效（count 0）——
        # 用 Playwright filter(has_text) 代替
        # S42-12：排除 label 内嵌套的控件（禅道 form-label 内的 checkbox
        # 快捷项 input#allBuilds 文档序在前，.first 会命中它而非 picker）
        # S43-4：逗号选择器按文档序取 first——hidden select（select2-
        # hidden-accessible）会抢在容器前。分两候选：先自绘控件容器，
        # 再原生控件（容器是用户真实点击目标）
        (frame.locator(".form-group, .ant-form-item", has_text=label)
         .locator(".select2-container, .picker, .ant-select, .ant-picker").first,
         "form-group-control"),
        (frame.locator(".form-group, .ant-form-item", has_text=label)
         .locator("input:not(label input), select:not(label select), "
                  "textarea:not(label textarea)").first,
         "form-group-native"),
        # S43-4：select2 下拉（Snipe-IT 等 bootstrap 系）——label 是渲染层
        # 文本（"Select Status"）或采集的相邻 select name。语义：含该 label
        # 的表单组内点 select2 容器（打开后由脚本链选值不可行——回放到此
        # 步骤只负责开下拉，值选择由 form-group 控件步或 API 断言覆盖）
        (frame.locator(".form-group, .ant-form-item, [class*=form-group]", has_text=label)
         .locator(".select2-container").first,
         "select2"),
        # S43-4：label 恰是相邻 select 的 name（采集侧 select2HostSelect 信号）
        (frame.locator(f'select[name="{label}"] ~ .select2-container').first,
         "select2-by-name"),
        (frame.get_by_text(label, exact=True), "text"),
        (frame.get_by_placeholder(label), "placeholder"),
        (frame.get_by_label(label), "label"),
        # 框架自动生成 id（antd rc_select_N 等）回退：采集侧 input-key 链可能
        # 抓到这类 id（元素无 placeholder/aria 时）——回放时按 id 兜底定位
        (frame.locator(f"#{label}"), "id"),
        # S35：无可访问名图标按钮的 name 属性兜底（采集侧 nameAttr 兜底链）
        (frame.locator(f'[name="{label}"]'), "name-attr"),
        # S42-8：图标按钮只有 title 提示（禅道 dtable 操作列 <a title="解决">
        # 无文本无 name）——采集侧 labels 含 title，回放须有对应策略
        (frame.locator(f'[title="{label}"]'), "title-attr"),
        # S36：Frappe（ERPNext）模态输入框的 data-fieldname 兜底。
        # 控件优先：字段包装 div 同带 data-fieldname 且 DOM 序在前，
        # fill 会命中不可填元素——先试 input/textarea/select 再试任意元素
        (frame.locator(
            f'input[data-fieldname="{label}"], textarea[data-fieldname="{label}"], '
            f'select[data-fieldname="{label}"]'), "data-fieldname"),
        (frame.locator(f'[data-fieldname="{label}"]'), "data-fieldname-any"),
        # S35：input[type=submit] 的 value 兜底（采集侧 inputValue 链）
        (frame.locator(f'input[value="{label}"]'), "input-value"),
        # S42-12：子串名匹配最后兜底（精确名/全策略未命中才用）
        (frame.get_by_role("button", name=label), "role-button-substr"),
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
            # S42：可见候选中优先 enabled——同名按钮首个可能 disabled
            # （若依受保护行的 修改/删除），点击 disabled 只会报错
            visible_idx: list[int] = []
            enabled_idx: list[int] = []
            for i in range(min(count, 10)):
                try:
                    if await locator.nth(i).is_visible():
                        visible_idx.append(i)
                        if await locator.nth(i).is_enabled():
                            enabled_idx.append(i)
                except Exception:
                    continue
            if not visible_idx:
                continue
            usable = enabled_idx or visible_idx
            # S42-9：容器真正在加载时元素可见可点但组件吞掉点击——视为
            # 未就绪重试。注意只认"活动加载态"（is-loading/spinning）：
            # 禅道表单的 load-indicator 是常驻 class（form load-indicator
            # form-ajax），当加载态会永久拦截 locate
            loading = False
            for i in usable[:3]:
                try:
                    loading = await locator.nth(i).evaluate(
                        "el => !!(el.closest('.is-loading, .ant-spin-spinning, "
                        ".loading'))")
                    if loading:
                        break
                except Exception:
                    continue
            if loading:
                continue
            if len(usable) > 1:
                in_modal = await _first_in_open_modal(page, locator, usable)
                if in_modal is not None:
                    return locator.nth(in_modal), strategy
            return locator.nth(usable[0]), strategy
    return None


async def _first_in_open_modal(page: Page, locator: Locator,
                               idx: list[int]) -> int | None:
    """多个可见匹配中，返回位于开放模态/对话框内的第一个下标（无则 None）。"""
    # S42：模态可能在子 frame（iframe 架构应用）——逐 frame 查
    has_modal = 0
    for fr in page.frames:
        try:
            has_modal += await fr.locator(
                ".modal.show, [role='dialog'][aria-modal='true'], [aria-modal='true']"
            ).count()
        except Exception:
            continue
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
    （path 祖先链 + ordinal nth-of-type，唯一命中才用——宁缺毋滥）。
    S42：iframe/SPA 内容异步加载（禅道综合界面 about:blank iframe 由
    JS 注入）——首查未命中时短暂重试再判失败。
    S42-9：重试窗口须覆盖模态框 AJAX 加载（禅道 resolve 模态 ~3-5s，
    3×1s 实测不够）——5×1s。"""
    for attempt in range(5):
        for lbl in [label, *(labels or [])]:
            if not lbl:
                continue
            hit = await _try_locate(page, lbl, prefer_controls=prefer_controls)
            if hit is not None:
                return hit
        if attempt < 4:
            await page.wait_for_timeout(1000)
    if path:
        segs = [s for s in path.split(">") if s]
        if segs:
            last = segs[-1]
            sel = " ".join(segs) if len(segs) == 1 else f"{' '.join(segs[:-1])} {last}"
            if ordinal and ordinal > 1:
                sel += f":nth-of-type({ordinal})"
            for fr in page.frames:
                locator = fr.locator(sel)
                try:
                    count = await locator.count()
                    if count == 1 and await locator.first.is_visible():
                        return locator.first, "structural"
                except Exception:
                    continue
    raise LookupError(f"semantic locate failed: {label!r}")
