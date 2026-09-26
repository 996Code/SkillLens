"""S18 T3：夜间开发自动执行器——浏览器自动化实现 dev_plan（常驻窗口可见）。

复用 S11 实测模式：打开设计器 → 加字段（点类型/改名改 key/权限 JS 注入）→
保存 → 抓 saveFormConfig 响应。每步落 execution_log（C3）。
"""
import asyncio
import json
import re
import time

from playwright.async_api import async_playwright
from sqlalchemy.orm import Session

from app.models import DevPlan

DESIGNER_URL = "http://192.168.99.22/mb3/1/mind-designer/field-edit?formCode={code}"

JS_CLICK_PERM = """
(label) => {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.textContent.trim() === label) {
      let el = node.parentElement;
      for (let i = 0; i < 6 && el; i++) {
        const sel = el.querySelector(':scope .n-base-selection');
        if (sel) { sel.dispatchEvent(new MouseEvent('click', {bubbles: true})); return 'opened'; }
        el = el.parentElement;
      }
      return 'no-selection';
    }
  }
  return 'not-found';
}
"""
JS_CLICK_ALL_OPTS = """
() => {
  const opts = document.querySelectorAll('.n-base-select-option');
  opts.forEach(o => o.dispatchEvent(new MouseEvent('click', {bubbles: true})));
  return opts.length;
}
"""


def compile_steps(changes: list[dict]) -> list[dict]:
    """变更清单 → 执行步骤序列（纯函数，单测覆盖）。"""
    steps: list[dict] = []
    for ch in changes:
        if ch.get("op") != "add_field":
            raise ValueError(f"不支持的 op: {ch.get('op')}")
        ftype = ch.get("field_type", "")
        if not ftype:
            raise ValueError("field_type 不能为空")
        steps.append({"action": "add_field", "field_type": ftype,
                      "label": ch.get("label", ""), "key": ch.get("key", "")})
    if not steps:
        raise ValueError("changes 为空")
    return steps


async def _add_field(page, step: dict, log: list) -> None:
    """加一个字段：点类型 → 改名/key → 权限注入。"""
    await page.get_by_text(step["field_type"], exact=True).first.click()
    await page.wait_for_timeout(1000)
    wraps = page.locator(".mind-admin-widget-config_displayarea .widget-wrap")
    n = await wraps.count()
    await wraps.nth(n - 1).click()
    await page.wait_for_timeout(800)
    try:
        await page.get_by_text("字段属性", exact=True).first.click(timeout=2000)
    except Exception:
        pass
    await page.wait_for_timeout(500)
    await page.get_by_placeholder("请输入字段名称").first.fill(step["label"])
    await page.wait_for_timeout(300)
    key_area = page.get_by_text("字段key", exact=False).first
    await key_area.locator("xpath=following::input[1]").fill(step["key"])
    await page.wait_for_timeout(300)
    # 权限三下拉（JS 注入，S11 模式）
    await page.evaluate("""() => {
      const panes = document.querySelectorAll('.n-tab-pane');
      for (const pane of panes) {
        const style = pane.style.display || '';
        if (style.includes('none')) continue;
        if ((pane.innerText||'').includes('字段名称')) pane.scrollTop = pane.scrollHeight;
      }
    }""")
    await page.wait_for_timeout(400)
    perms = {}
    for label in ("新增时可见", "查看时可见", "可编辑"):
        await page.evaluate(JS_CLICK_PERM, label)
        await page.wait_for_timeout(600)
        cnt = await page.evaluate(JS_CLICK_ALL_OPTS)
        perms[label] = cnt
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(250)
    log.append({"step": "add_field", "label": step["label"], "key": step["key"],
                "perms": perms})


async def execute_dev_plan(db: Session, plan: DevPlan) -> DevPlan:
    """执行已确认的开发计划（C1：仅 confirmed 可达——API 层门控）。"""
    log: list[dict] = [{"step": "start", "target_form": plan.target_form,
                        "changes": len(plan.changes or [])}]
    try:
        steps = compile_steps(plan.changes or [])
    except ValueError as e:
        plan.status = "error"
        plan.execution_log = log + [{"step": "compile", "error": str(e)}]
        db.commit()
        return plan

    cdp = None
    from app.replay.runner import _cdp_url
    cdp = _cdp_url()
    try:
        async with async_playwright() as p:
            if cdp:
                browser = await p.chromium.connect_over_cdp(cdp)
                ctx = next((c for c in browser.contexts if c.service_workers),
                           browser.contexts[0])
                own_browser = False
            else:
                browser = await p.chromium.launch(headless=False)
                ctx = await browser.new_context()
                own_browser = True
            try:
                page = await ctx.new_page()
                await page.goto(DESIGNER_URL.format(code=plan.target_form))
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2500)
                log.append({"step": "designer_opened",
                            "url": page.url[:80]})
                for step in steps:
                    await _add_field(page, step, log)
                # 保存并抓响应
                result = {}

                async def on_resp(resp):
                    if "saveFormConfig" in resp.url:
                        try:
                            result["status"] = resp.status
                            result["body"] = (await resp.text())[:150]
                        except Exception:
                            pass
                page.on("response", on_resp)
                await page.get_by_role("button", name="保存").click()
                await page.wait_for_timeout(4000)
                log.append({"step": "saved", "save_response": result})
                await page.close()
                if result.get("status") == 200 and '"code":200' in (result.get("body") or ""):
                    plan.status = "executed"
                else:
                    plan.status = "error"
            finally:
                if own_browser:
                    await browser.close()
                else:
                    await browser.close()  # CDP 仅断连
    except Exception as exc:
        plan.status = "error"
        log.append({"step": "exception", "error": str(exc)[:200]})
    plan.execution_log = log
    db.commit()
    db.refresh(plan)
    return plan
