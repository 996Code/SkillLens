"""JeecG 链式 override：row-anchor 换参注入 + 断言动态 id 归一（S43-4 未竟项收尾）。

两个确定性单元（真机行为）：
1. execute_plan 的 row_anchor_hints——换参回放时行点击步的宿主行文本
   （录制时旧表名）跨轮必然陈旧，override 值（新表名）必须能注入行过滤；
2. evaluate_assertions 的 state_signal expect_value 动态实体标识
   （纯数字≥12 位 / hex≥16 位）——跨轮 id 天然漂移，记录不判定
   （与 URL 层 _ID_SEGMENT / S42 行上下文同哲学）。
"""
import re

from app.replay.runner import execute_plan, _row_anchor_token
from app.replay.assert_eval import evaluate_assertions

ROW_TABLE_HTML = """
<html><body>
  <table class="ant-table-row-table"><tbody>
    <tr class="ant-table-row"><td><span>更多</span></td><td>sl_form_a26513 SL表单a</td></tr>
    <tr class="ant-table-row"><td><span>更多</span></td><td>sl_rp4242 SL回放表单</td></tr>
  </tbody></table>
</body></html>
"""


async def test_row_click_uses_override_row_anchor():
    """换参行点击：labels 是录制行文本（旧表名），row_anchor_hints 注入
    新表名后行过滤命中新行——点的是第二行的"更多"。"""
    async with _pw() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=ROW_TABLE_HTML))
        await page.goto("http://mock.local/")
        await page.evaluate("""() => {
          window.__clicked = [];
          document.querySelectorAll('tr').forEach((tr, i) => {
            tr.querySelector('span').addEventListener('click',
              () => window.__clicked.push(i));
          });
        }""")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "click", "label": "更多",
             "labels": ["更多", "sl_form_a26513 SL表单a26513 20261001"]},
        ]}
        result = await execute_plan(
            page, plan, row_anchor_hints=["sl_rp4242"])
        clicked = await page.evaluate("window.__clicked")
        await browser.close()
    assert result["executed"][0]["ok"] is True
    assert result["executed"][0]["strategy"] == "row-trigger"
    assert clicked == [1], "行锚未按 override 新表名命中第二行"


async def test_row_click_without_hint_falls_back_to_labels():
    """无 hints：保持旧行为——labels 旧表名能录到哪行就哪行（回归护栏）。"""
    async with _pw() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=ROW_TABLE_HTML))
        await page.goto("http://mock.local/")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "click", "label": "更多",
             "labels": ["更多", "sl_form_a26513 SL表单a26513"]},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert result["executed"][0]["ok"] is True
    assert result["executed"][0]["strategy"] == "row-trigger"


def test_state_signal_numeric_id_expect_is_recorded_not_judged():
    """动态实体 id 期望（纯数字 19 位——JeecG online form code 派生）：
    跨轮回放命中行≠录制行，值天然漂移 → passed=True + skipped 标注。"""
    observed = [{"url": "http://t/online/cgform/api/form/abc",
                 "status": 200, "method": "POST",
                 "body": '{"result": "2105930111222333444", "code": 200}'}]
    results = evaluate_assertions(
        [{"kind": "state_signal",
          "payload": {"api_template": "/online/cgform/api/form/{id}",
                      "field": "result", "expect_value": "2105924991050280962",
                      "url_path": "/online/cgform/api/form/x"}}],
        observed)
    assert results[0]["passed"] is True
    assert results[0]["skipped"] and "动态" in results[0]["skipped"]


def test_state_signal_hex_id_expect_is_recorded_not_judged():
    """hex 32 位（JeecG online 表 code）同为跨会话实体标识。"""
    observed = [{"url": "http://t/api/x", "status": 200, "method": "POST",
                 "body": '{"result": "88086f4fee37479e8f482006b50c840a"}'}]
    results = evaluate_assertions(
        [{"kind": "state_signal",
          "payload": {"api_template": "/api/x", "field": "result",
                      "expect_value": "88086f4fee37479e8f482006b50c840a"}}],
        observed)
    assert results[0]["passed"] is True
    assert results[0]["skipped"]


def test_state_signal_stable_expect_still_judged():
    """稳定期望值（业务文本/短数字）不受动态门影响——判定语义不得泛化放宽。"""
    observed = [{"url": "http://t/api/x", "status": 200, "method": "POST",
                 "body": '{"result": "添加成功!", "code": 200}'}]
    hit = evaluate_assertions(
        [{"kind": "state_signal",
          "payload": {"api_template": "/api/x", "field": "result",
                      "expect_value": "添加成功!"}}],
        observed)
    miss = evaluate_assertions(
        [{"kind": "state_signal",
          "payload": {"api_template": "/api/x", "field": "result",
                      "expect_value": "别的成功文案"}}],
        observed)
    assert hit[0]["passed"] is True and hit[0].get("skipped") is None
    assert miss[0]["passed"] is False


def _pw():
    from playwright.async_api import async_playwright
    return async_playwright()
