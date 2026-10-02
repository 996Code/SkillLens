from playwright.async_api import Locator, Page


def _xpath_str(s: str) -> str:
    """XPath 1.0 字符串字面量（含引号时用 concat 拼接）。"""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


async def _try_locate(page: Page, label: str,
                      prefer_controls: bool = False) -> tuple[Locator, str] | None:
    # S42：iframe 架构应用（禅道综合界面等）业务内容渲染在子 frame——
    # 逐 frame 尝试候选策略（主 frame 优先）
    frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
    # S43-4 第一轮：强语义（精确名/title/name）全 frame 优先
    for frame in frames:
        hit = await _try_locate_in_frame(page, frame, label, prefer_controls,
                                         strong_only=True)
        if hit is not None:
            return hit
    for frame in frames:
        hit = await _try_locate_in_frame(page, frame, label, prefer_controls)
        if hit is not None:
            return hit
    return None


async def _try_locate_in_frame(page: Page, frame, label: str,
                               prefer_controls: bool,
                               strong_only: bool = False) -> tuple[Locator, str] | None:
    # S43-4：两级遍历——强语义（精确按钮名/title/name）在所有 frame 上
    # 先跑一轮，弱策略（text）第二轮才跑。禅道实测：iframe 业务页的
    # 图标操作（a[title=执行]）与顶层菜单纯文本"执行"同名——按
    # frame×策略全序遍历时主 frame 的 text 抢在 iframe 的 title 前命中，
    # 点错元素导航走错页
    if strong_only:
        # S43-4 第一轮只做一件事：全 frame 找可见的 [title=] 命中——
        # title 是图标操作的唯一标识（禅道 dtable 行操作），任何 frame
        # 的 text 命中都不该抢在它前面。其余强语义（role-button 精确
        # 名等）留在第二轮原序（避免绕过 enabled/loading 判定）
        # S43-4：排除导航容器（ERPNext sidebar-item-container 带
        # title=Quotation 抢走下拉菜单项点击）；fill 场景跳过整轮——
        # grid 单元格 div 也带 title（Item Code），fill 须走控件策略
        if prefer_controls:
            return None
        locator = frame.locator(f'[title="{label}"]')
        try:
            count = await locator.count()
        except Exception:
            return None
        for i in range(min(count, 10)):
            try:
                el = locator.nth(i)
                if not await el.is_visible():
                    continue
                bad = await el.evaluate(
                    "e => !!e.closest('.sidebar, .nav, .menu, [class*=sidebar], "
                    "[class*=navbar], [class*=nav-link]')")
                if bad:
                    continue
                return el, "title-attr"
            except Exception:
                continue
        return None
    candidates: list[tuple[Locator, str]] = [
        # S42-12：精确名优先——get_by_role(name=) 默认子串匹配，禅道 Bug
        # 表单的"保存模板"会抢在真提交按钮"保存"之前命中（点击只触发
        # 模板面板不开提交）。子串匹配降级为最后兜底。
        (frame.get_by_role("button", name=label, exact=True), "role-button"),
    ]
    # S43-4：短 label（checkbox 的 value="on" 等）禁用子串型容器策略
    # （form-group has_text="on" 会命中任何含 Contact/Section 文本的
    # 表单组，抢走点击目标）；label 同取精确
    short_label = len(label) <= 3
    if not short_label:
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
        candidates += [
            (frame.locator(".form-group, .ant-form-item", has_text=label)
             .locator(".select2-container, .picker, .ant-select, .ant-picker").first,
             "form-group-control"),
            (frame.locator(".form-group, .ant-form-item", has_text=label)
             .locator("input:not(label input), select:not(label select), "
                      "textarea:not(label textarea)").first,
             "form-group-native"),
        ]
    candidates += [
        # S43-4：select2 下拉（Snipe-IT 等 bootstrap 系）——label 是渲染层
        # 文本（"Select Status"）或采集的相邻 select name。语义：含该 label
        # 的表单组内点 select2 容器（打开后由脚本链选值不可行——回放到此
        # 步骤只负责开下拉，值选择由 form-group 控件步或 API 断言覆盖）
        # S43-4：短 label 跳过（has_text 子串误命中）
        # S43-4：label 恰是相邻 select 的 name（采集侧 select2HostSelect 信号）
        (frame.locator(f'select[name="{label}"] ~ .select2-container').first,
         "select2-by-name"),
        # S43-4：title 提前——禅道 dtable 图标行操作（a[title=执行] 无文本）
        # 的唯一标识是 title；text 策略会误中侧边菜单同名项导航走错页。
        # 同 strong_only：排除导航容器（ERPNext sidebar 带同名 title 抢
        # 走下拉菜单项点击）
        (frame.locator(
            f'xpath=//*[@title={_xpath_str(label)} and not(ancestor-or-self::*['
            f'contains(@class, "sidebar") or contains(@class, "navbar") or '
            f'contains(@class, "nav-link")])]'
        ), "title-attr"),
        # S43-4：菜单项语义（role=menuitem / 下拉项）优先于裸 text——
        # 裸 text 会命中侧边栏同名导航文本（ERPNext 实测点击后整页
        # 导航走错）
        (frame.locator(
            f'xpath=//*[@role="menuitem" or @role="option" or @role="menu"]'
            f'[normalize-space(.)={_xpath_str(label)}]'), "menuitem"),
        # S43-4：text 命中的 tooltip span（Frappe 字段小问号提示内容恰是
        # 字段名）不可点——排除 tooltip/aria-hidden 载体；同时排除导航
        # 容器（同 title：sidebar 同名文本点击会整页导航走错）
        (frame.locator(
            f'xpath=//*[normalize-space(text())={_xpath_str(label)} and '
            f'not(ancestor-or-self::*[contains(@class,"tooltip") '
            f'or @aria-hidden="true" or contains(@class, "sidebar") '
            f'or contains(@class, "navbar") or contains(@class, "nav-link")])]'
            f'[1]'),
         "text"),
        # S43-4：placeholder 精确匹配——checkbox 的 value="on" 会成为
        # 采集 label，子串匹配意外命中任何含 "on" 的 placeholder/杂项
        (frame.get_by_placeholder(label, exact=True), "placeholder"),
        # S43-4：element-plus el-select 空 placeholder 渲染为
        # .el-select__placeholder 容器内的裸 span 文本（非 input 属性）
        # ——录制点击抓到该文本；点击 span 不开下拉，须点 el-select 容器
        (frame.locator(
            '.el-select:has(.el-select__placeholder)').filter(
            has_text=label).first,
         "el-select-placeholder"),
        (frame.get_by_label(label, exact=True) if short_label
         else frame.get_by_label(label), "label"),
        # 框架自动生成 id（antd rc_select_N 等）回退：采集侧 input-key 链可能
        # 抓到这类 id（元素无 placeholder/aria 时）——回放时按 id 兜底定位
        (frame.locator(f"#{label}"), "id"),
        # S35：无可访问名图标按钮的 name 属性兜底（采集侧 nameAttr 兜底链）
        (frame.locator(f'[name="{label}"]'), "name-attr"),
        # S36：Frappe（ERPNext）模态输入框的 data-fieldname 兜底。
        # 控件优先：字段包装 div 同带 data-fieldname 且 DOM 序在前，
        # fill 会命中不可填元素——先试 input/textarea/select 再试任意元素
        (frame.locator(
            f'input[data-fieldname="{label}"], textarea[data-fieldname="{label}"], '
            f'select[data-fieldname="{label}"]'), "data-fieldname"),
        (frame.locator(f'[data-fieldname="{label}"]'), "data-fieldname-any"),
        # S35：input[type=submit] 的 value 兜底（采集侧 inputValue 链）。
        # S43-4：布尔 label（checkbox）——checkbox 的 value=on 是 JS
        # property 非 attribute（CSS [value=] 属性选择器不命中）。
        # 行内 checkbox 优先（列表勾选场景——表头全选框语义不同，
        # Frappe 表头框被 JS 覆写状态 check() 会报 did not change）
        (frame.locator(
            '.list-row-check, .list-row-checkbox, '
            '.grid-row:not(.grid-header-row) input[type="checkbox"]')
         if label in ("on", "off", "true", "false", "1", "0")
         else frame.locator(f'input[value="{label}"]'), "input-value"),
        # S42-12：子串名匹配最后兜底（精确名/全策略未命中才用）。
        # S43-4：词边界约束——'on' 不得命中 'Make Quotation'（子串
        # 无边界）、'Get Items' 不得命中 'Get Items From'（匹配后
        # 还有续词=命中的是更长的不同按钮）。按词集相等或 label 是
        # 按钮名的连续词前缀子串（去尾词后完全一致）
        (frame.get_by_role("button", name=_substr_pattern(label)),
         "role-button-substr"),
    ]
    if not short_label:
        candidates.append(
            (frame.locator(".form-group, .ant-form-item, [class*=form-group]",
                           has_text=label).locator(".select2-container").first,
             "select2"))
    if prefer_controls:
        # S36：fill 场景控件优先——Frappe 把字段名渲染成可见帮助文本，
        # text/role 策略会抢先命中文本节点（不可填），控件类策略前置
        # S43-4：fill 场景剔除 data-fieldname-any（字段包装 div 同带
        # data-fieldname，fill 必抛"not an input"——Frappe 行编辑实测）
        order = ["placeholder", "label", "name-attr", "data-fieldname",
                 "id", "input-value", "role-button", "text"]
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
    # S43-4：导航/重渲窗口（Save 后页面跳转详情页再渲染）需更长
    # 重试——5×1s 实测不够（ERPNext Submit 按钮在写请求+页面刷新
    # 后 ~4.5s 才出现），扩到 8 轮
    for attempt in range(12):
        for lbl in [label, *(labels or [])]:
            if not lbl:
                continue
            hit = await _try_locate(page, lbl, prefer_controls=prefer_controls)
            if hit is not None:
                return hit
        if attempt < 11:
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
    # S43-4 评分兜底（Healenium 式）：语义策略与结构路径全失败后，
    # 对页面可交互元素做确定性多信号评分——top1 达阈值且与 top2 拉开
    # 差距才命中（消歧 'on' 误中 party_name / 'Get Items' vs
    # 'Get Items From' 这类前缀/子串歧义）
    hit = await _scored_fallback(page, label, labels or [], tag, ordinal, path)
    if hit is not None:
        return hit
    raise LookupError(f"semantic locate failed: {label!r}")


# S43-4 评分兜底：可交互元素候选集 + 确定性多信号评分（页面内 JS 一趟完成）
_SCORE_JS = """(args) => {
  const label = args.label, labels = args.labels, wantTag = (args.tag || '').toLowerCase();
  const candidates = Array.from(document.querySelectorAll(
    'button, input, select, textarea, a, [role="button"], [role="checkbox"], [role=option]'));
  const scored = [];
  for (const el of candidates) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (!el.isConnected) continue;
    const text = (el.textContent || '').trim();
    const value = String(el.value !== undefined ? el.value : '');
    const name = el.getAttribute('name') || '';
    const id = el.id || '';
    const ph = el.getAttribute('placeholder') || '';
    const title = el.getAttribute('title') || '';
    const aria = el.getAttribute('aria-label') || '';
    const all = [label, ...labels].filter(Boolean);
    let score = 0;
    for (const lbl of all) {
      if (text === lbl) score += 5;
      else if (value === lbl) score += 5;
      else if (name === lbl) score += 5;
      else if (id === lbl) score += 5;
      else if (ph === lbl) score += 5;
      else if (title === lbl) score += 5;
      else if (aria === lbl) score += 5;
      else if (lbl.length > 3 && text.includes(lbl)) score += 3;
      else if (lbl.length > 3 && value.includes(lbl)) score += 3;
      else if (lbl.length > 3 && title.includes(lbl)) score += 3;
    }
    if (wantTag && el.tagName.toLowerCase() === wantTag) score += 1;
    if (el.closest('.modal.show, .modal[style*="display: block"], [role=dialog]')) score += 2;
    if (el.offsetParent !== null) score += 1;
    if (score > 0) scored.push({score, i: candidates.indexOf(el)});
  }
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, 3);
}"""


async def _scored_fallback(page: Page, label: str, labels: list[str],
                           tag: str | None, ordinal: int | None,
                           path: str | None) -> tuple[Locator, str] | None:
    """全语义策略失败后的确定性评分兜底。阈值语义：top1 >= 5（至少
    一个强信号精确命中）且 top1 - top2 >= 2（消歧），否则宁缺毋滥。"""
    for fr in page.frames:
        try:
            results = await fr.evaluate(
                _SCORE_JS, {"label": label, "labels": labels, "tag": tag})
        except Exception:
            continue
        if not results:
            continue
        top = results[0]
        if top["score"] < 5:
            continue
        if len(results) > 1 and top["score"] - results[1]["score"] < 2:
            continue
        locator = fr.locator(
            "button, input, select, textarea, a, [role='button'], "
            "[role='checkbox'], [role=option]").nth(top["i"])
        try:
            if await locator.is_visible():
                return locator, "scored"
        except Exception:
            continue
    return None


def _substr_pattern(label: str) -> "re.Pattern":
    """子串按钮名的词边界 regex。

    多词 label 整名锚定（词序完整、无续词）——'Get Items' 不吃
    'Get Items From'，'on' 不吃 'Make Quotation'；单词/中文 label
    保持词界子串（禅道 '保存' 命中长按钮名场景）。
    """
    import re as _re
    words = [_re.escape(w) for w in label.split() if w]
    if not words:
        return _re.compile(r"^\u0000$")
    has_cjk = any(any('\u4e00' <= c <= '\u9fff' for c in w) for w in label)
    body = r"[\s\u00a0]*".join(words)
    if len(words) > 1:
        return _re.compile(rf"^{body}$")
    if has_cjk:
        return _re.compile(body)  # 中文无词界，子串即语义
    # 拉丁单词：两侧词界（\b 对空格边界即词首尾）
    return _re.compile(rf"\b{body}\b")
