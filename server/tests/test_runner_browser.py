import json

from playwright.async_api import async_playwright

from app.replay.runner import execute_plan

FORM_HTML = """
<html><body>
  <input placeholder="请输入" />
  <button role="button">保存</button>
</body></html>
"""


async def test_execute_plan_semantic_locate():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # R1: 固定 mock origin，避免 about:blank 上相对 fetch 解析失败；charset 防 UTF-8 被按 Latin-1 解码
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        calls = []

        async def handle_save(route):
            calls.append(route.request.url)
            await route.fulfill(status=200, body='{"code":200}')

        await page.route("**/api/save", handle_save)
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "请输入", "value": "v1", "original_value": "o"},
            {"kind": "click", "label": "保存"},
        ]}
        # 注入一个真实触发 fetch 的按钮行为（绝对 URL，确保 route **/api/save 捕获）
        await page.evaluate("""() => {
          document.querySelector('button').addEventListener('click',
            () => fetch('http://mock.local/api/save', {method: 'POST'}));
        }""")
        result = await execute_plan(page, plan)
        await browser.close()
    assert [s["ok"] for s in result["executed"]] == [True, True]
    assert result["executed"][0]["strategy"] in ("placeholder",)
    assert len(result["observed"]) == 1 and result["observed"][0]["status"] == 200
    assert len(calls) == 1


async def test_execute_plan_stops_on_missing_element():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(FORM_HTML)
        plan = {"url": "about:blank", "steps": [
            {"kind": "click", "label": "不存在的按钮"},
            {"kind": "click", "label": "保存"},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert result["executed"][0]["ok"] is False
    assert result["executed"][1]["ok"] is False and result["executed"][1]["error"] == "not attempted"
