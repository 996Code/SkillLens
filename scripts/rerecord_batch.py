"""重录批：Snipe 304（列表流借出）+314（行内 Update）+Odoo 296（报价创建）。

语料级修复（链回归终轮定性）：旧录制含实例段 goto（/hardware/18/checkout）
/action id 漂移（Odoo #107）——重录为干净流（列表入口/行操作/菜单路径）。

用法：cd server && RECORD_CDP_URL=http://127.0.0.1:9222 uv run python
../scripts/rerecord_batch.py
"""
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710/api/v1"
SNIPE = "http://127.0.0.1:8081"
ODOO = "http://127.0.0.1:8069"


async def find_service_worker(ctx):
    for _ in range(30):
        for w in ctx.service_workers:
            if "service-worker-loader" in w.url or "uploader" in w.url:
                return w
        await asyncio.sleep(1)
    raise RuntimeError("extension service worker 未找到")


async def ext_call(ctx, sw, msg: dict):
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))",
            msg)
    finally:
        await page.close()


async def record_flow(ctx, page, note: str, flow) -> str | None:
    sw = await find_service_worker(ctx)
    r = await ext_call(ctx, sw, {"type": "START_RECORDING", "note": note,
                                 "source": "demo"})
    sid = (r or {}).get("id", "")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await flow(page)
    except Exception as e:
        print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:120]}")
    await page.wait_for_timeout(1500)
    await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
    await page.wait_for_timeout(2500)
    return sid


async def flow_snipe_checkout(page) -> None:
    """304 重录（列表流）：列表→行 Checkout→选用户→Checkout 确认。"""
    await page.goto(f"{SNIPE}/hardware")
    await page.wait_for_timeout(4000)
    # 第一行的 Checkout 行操作（title 型 icon 链接）
    row = page.locator("table tbody tr").first
    await row.locator("a[title='Checkout']").click()
    await page.wait_for_timeout(3000)
    # 选用户（select2）
    await page.evaluate("""() => {
      const sel = document.querySelector('select[name=assigned_to]');
      if (sel && window.jQuery) jQuery(sel).select2('open');
    }""")
    await page.wait_for_timeout(1500)
    await page.locator(".select2-results__option").first.click()
    await page.wait_for_timeout(1000)
    await page.locator("button", has_text="Checkout").last.click()
    await page.wait_for_timeout(3000)


async def flow_snipe_row_update(page) -> None:
    """314 重录（列表流）：列表→行 Update（进编辑页）。"""
    await page.goto(f"{SNIPE}/hardware")
    await page.wait_for_timeout(4000)
    row = page.locator("table tbody tr").first
    await row.locator("a[title='Update']").click()
    await page.wait_for_timeout(3000)


async def flow_odoo_quote(page) -> None:
    """296 重录（菜单路径）：销售→报价单→New→填客户→确认。"""
    await page.goto(f"{ODOO}/web#action=sale.action_quotations")
    await page.wait_for_timeout(6000)
    await page.locator("button", has_text="New").first.click()
    await page.wait_for_timeout(3000)
    # 客户字段（Odoo 关系字段——输入回车）
    await page.keyboard.type("Azure Interior", delay=50)
    await page.wait_for_timeout(1500)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2000)
    await page.locator("button", has_text="Confirm").first.click()
    await page.wait_for_timeout(3000)


async def process_and_learn(token: str, sid: str):
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        await c.post(f"{SERVER}/sessions/{sid}/process")
        resp = await c.post(f"{SERVER}/align", json={"session_ids": [sid, sid]})
        aid = resp.json()["alignment_id"]
        skill = None
        for _ in range(3):
            resp = await c.post(f"{SERVER}/alignments/{aid}/induce")
            if resp.status_code == 200:
                skill = resp.json()
                break
        if not skill:
            return None
        print(f"  induce: skill #{skill['id']} {skill['name']}")
        await c.post(f"{SERVER}/skills/{skill['id']}/assertions")
        return skill["id"]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        token = (await c.post(f"{SERVER}/auth/plugin-session")).json()["token"]
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = next((c for c in browser.contexts if c.service_workers),
                   browser.contexts[0])
        page = await ctx.new_page()
        results = {}
        for note, flow, key in (
                ("rerecord-snipe-checkout", flow_snipe_checkout, "snipe_checkout"),
                ("rerecord-snipe-update", flow_snipe_row_update, "snipe_update"),
                ("rerecord-odoo-quote", flow_odoo_quote, "odoo_quote")):
            print(f"== 录制 {note} ==")
            sid = await record_flow(ctx, page, note, flow)
            if sid:
                sk = await process_and_learn(token, sid)
                results[key] = sk
        await page.close()
        print("\n重录结果:", results)


if __name__ == "__main__":
    asyncio.run(main())
