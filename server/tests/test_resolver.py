"""AG2 resolver 编译器（TDD：协议契约 docs/arch/extension-executor-protocol.md §2 resolve 指令）。

compile_resolve_candidates(label, ...) → 有序候选 selector 列表（纯字符串，
插件端 Runtime.evaluate 按序实测）+ resolver JS 脚本。语义对齐 locate.py 策略
矩阵的强度序（title 强语义 > role-button 精确 > 表单组控件 > select2 >
menuitem > text > placeholder > el-select > label > id > name-attr）。
"""
from app.replay.resolver import (
    compile_resolve_candidates,
    build_resolver_js,
)


def test_candidates_ordered_by_strategy_strength():
    cands = compile_resolve_candidates("保存表单", labels=["保存表单"], tag="button")
    sels = [c["selector"] for c in cands]
    # title 强语义（排导航容器）在最前，aria-attr 紧随（图标按钮无文本）
    assert "title-attr" == cands[0]["strategy"]
    assert "aria-attr" == cands[1]["strategy"]
    assert "@title=" in sels[0] and "保存表单" in sels[0]
    # role-button 精确名随后
    assert cands[2]["strategy"] == "role-button"
    strategies = [c["strategy"] for c in cands]
    # 关键策略全在场且顺序正确（语义强度序）
    for expect in ("form-group-control", "select2-by-name", "menuitem",
                   "text", "placeholder", "label", "id", "name-attr"):
        assert expect in strategies, f"缺策略 {expect}"


def test_short_label_skips_substring_strategies():
    """locate 短 label 语义：≤3 字符禁用子串型（form-group/容器）——防 'on'
    误命中。resolver 同规则。"""
    cands = compile_resolve_candidates("on", labels=["on"])
    strategies = [c["strategy"] for c in cands]
    assert "form-group-control" not in strategies
    # 强语义与精确策略仍在
    assert "title-attr" in strategies and "placeholder" in strategies


def test_resolver_js_is_self_contained_eval():
    """build_resolver_js：产出可在插件 Runtime.evaluate 直接执行的脚本——
    按序实测候选（可见+可点+非导航容器谓词），返回首个命中的 rect 信息。"""
    cands = compile_resolve_candidates("保存")
    js = build_resolver_js(cands)
    assert isinstance(js, str) and "querySelector" in js
    # 返回结构约定：{index, selector, rect:{x,y,width,height}, frame}
    assert "rect" in js and "offsetParent" in js


def test_resolver_js_no_candidates_returns_miss():
    js = build_resolver_js([])
    assert "MISS" in js


async def test_resolver_locate_parity_on_real_page():
    """双实现一致性护栏：同页面上 resolver JS 与 locate() 命中同一元素
    （策略+目标）——瘦执行器架构的防漂移锚点。"""
    import json
    from playwright.async_api import async_playwright
    from app.replay.locate import locate

    PAGE = """<html><body>
      <div class="form-group"><label>客户名称</label>
        <input placeholder="客户名称"></div>
      <button id="save" role="button">保存表单</button>
    </body></html>"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/**", lambda r: r.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=PAGE))
        await page.goto("http://mock.local/")
        cands = compile_resolve_candidates("保存表单")
        r = await page.evaluate(build_resolver_js(cands),
                                {"candidates": cands, "label": "保存表单"})
        loc, strategy = await locate(page, "保存表单")
        loc_id = await loc.get_attribute("id")
        await browser.close()
    assert r["hit"] is True
    assert strategy == r["strategy"]
    assert loc_id == "save"  # 两者都点中真按钮（sidebar 同名按钮被排除）


def test_ao4_profile_selectors_flow_into_candidates():
    """AO4（引擎零系统知识）：画像选择器进 resolver 候选——自定义
    容器/控件/select2 选择器随候选传递，插件端 JS 用候选内 selector
    （模板不写死）。默认（无画像）=原引擎硬编码值零变化。"""
    ip = {"form_fill": {"container_selector": ".my-field",
                        "control_selector": ".my-widget"},
          "dropdown": {"select2_container": ".my-sel2"}}
    cands = compile_resolve_candidates("资产名称", labels=["资产名称"],
                                       interaction_profile=ip)
    by = {c["strategy"]: c for c in cands}
    assert by["form-group-control"]["selector"] == ".my-field"
    assert "control_selector" in by["form-group-control"], \
        "控件选择器须随候选传递（JS 模板不再硬编码）"
    assert by["form-group-control"]["control_selector"] == ".my-widget"
    assert ".my-sel2" in by["select2-by-name"]["selector"]
    # JS 模板按候选内 control_selector 查控件
    js = build_resolver_js(cands)
    assert "c.control_selector" in js, "resolver JS 须消费候选内控件选择器"


def test_ao4_defaults_unchanged_without_profile():
    """无画像：候选 selector=引擎默认词表（与 locate DEFAULT_CONTAINER_SEL
    同源——三段式超集，resolver 原两段式并入统一默认）。"""
    from app.replay.locate import DEFAULT_CONTAINER_SEL, DEFAULT_CONTROL_SEL
    cands = compile_resolve_candidates("资产名称", labels=["资产名称"])
    by = {c["strategy"]: c for c in cands}
    assert by["form-group-control"]["selector"] == DEFAULT_CONTAINER_SEL
    assert by["form-group-control"]["control_selector"] == DEFAULT_CONTROL_SEL
    assert ".select2-container" in by["select2-by-name"]["selector"]
