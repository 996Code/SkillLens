"""AO1（引擎零系统知识）：画像选择器外置的服务端行为测试。

范围：execute_plan 消费 interaction_profile——校验错误选择器加法、
表单容器/控件选择器、select2 引擎声明。默认值=原引擎硬编码（无画像
零行为变化），画像声明可扩展/覆盖。
"""
from playwright.async_api import async_playwright

from app.replay.runner import execute_plan


async def test_execute_plan_profile_validation_selector_added():
    """画像 validation_error_selector 是加法：自定义错误类名（引擎
    默认词表不含）探测得到——新系统错误元素不用改引擎源码。"""
    html = """
    <html><body>
      <input placeholder="请输入" />
      <button role="button">保存</button>
      <div class="my-err" style="display:none">必填项不能为空</div>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))
        await page.goto("http://mock.local/")
        # 点击保存后显示自定义错误（无写请求=校验拦截场景）
        await page.evaluate("""() => {
          document.querySelector('button').addEventListener('click', () => {
            document.querySelector('.my-err').style.display = 'block';
          });
        }""")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "请输入", "value": "v1", "original_value": "o"},
            {"kind": "click", "label": "保存"},
        ]}
        profile = {"form_fill": {
            "validation_error_selector": ".my-err"}}
        result = await execute_plan(page, plan,
                                    interaction_profile=profile)
        await browser.close()
    click_step = result["executed"][1]
    assert "必填项不能为空" in (click_step.get("validation_errors") or []), \
        "画像声明的自定义校验错误类应被探测"


async def test_execute_plan_profile_form_container():
    """画像 container_selector：自定义表单容器类（引擎默认词表不含）
    内的控件可定位——label 在容器上、input 是真控件的自定义框架。"""
    html = """
    <html><body>
      <div class="my-field"><label>资产名称</label><input /></div>
      <button role="button">提交</button>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))
        await page.goto("http://mock.local/")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "资产名称", "value": "v1", "original_value": "o"},
        ]}
        profile = {"form_fill": {
            "container_selector": ".my-field",
            "control_selector": "input, select, textarea"}}
        result = await execute_plan(page, plan,
                                    interaction_profile=profile)
        await browser.close()
    assert result["executed"][0]["ok"] is True, result["executed"]


async def test_execute_plan_select2_protocol_from_profile():
    """AO3：select2 fill 协议按画像 engine 驱动——engine=select2 且选择器
    组从画像读；自定义容器/选项类名（引擎默认词表不含）可命中。"""
    html = """
    <html><body>
      <div class="my-sel2"><span class="my-sel2-rendered">状态</span></div>
      <select name="状态" style="display:none"></select>
      <button role="button">保存</button>
      <div class="my-sel2-drop" style="display:none">
        <ul><li class="my-sel2-opt">在用</li></ul>
      </div>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=html))
        await page.goto("http://mock.local/")
        # 点容器开"下拉"，点选项
        await page.evaluate("""() => {
          document.querySelector('.my-sel2').addEventListener('click', () => {
            document.querySelector('.my-sel2-drop').style.display = 'block';
          });
          document.querySelector('.my-sel2-opt').addEventListener('click', () => {
            window.__picked = true;
          });
        }""")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "状态", "value": "在用",
             "original_value": "o"},
        ]}
        profile = {"dropdown": {
            "engine": "select2",
            "select2_container": ".my-sel2",
            "select2_open_state": ".my-sel2-drop .my-sel2-opt",
            "select2_search_field": "input.my-nosearch",
            "select2_option": ".my-sel2-opt"}}
        result = await execute_plan(page, plan,
                                    interaction_profile=profile)
        await browser.close()
    step = result["executed"][0]
    assert step["ok"] is True, result["executed"]
