"""S43-4：Odoo 销售链闭环——报价单→确认→创建发票。

Odoo 17 要点：菜单是 SPA hash 路由（/web#action=sale.action_quotations
直达）；表单控件是 owl 自绘（name 输入是 div[contenteditable] 或
placeholder 输入框）；客户字段是 many2one 下拉（输入搜索→选结果）。

用法：cd server && ODOO_PW=... PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_odoo_sales.py
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
ODOO = "http://127.0.0.1:8069"
ODOO_USER = "admin@local.test"
QUOTATIONS = f"{ODOO}/web#action=sale.action_quotations"


def mint_token() -> str:
    from app.auth import issue_token
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin").first()
        return issue_token(db, u.id)
    finally:
        db.close()


async def find_service_worker(ctx):
    import asyncio as _aio
    deadline = _aio.get_event_loop().time() + 20
    while _aio.get_event_loop().time() < deadline:
        for w in ctx.service_workers:
            if 'service-worker-loader' in w.url or 'uploader' in w.url:
                return w
        await _aio.sleep(1)
    raise RuntimeError('extension service worker 未找到')


async def ext_call(ctx, sw, msg: dict) -> object:
    ext_id = sw.url.split('/')[2]
    page = await ctx.new_page()
    try:
        await page.goto(f'chrome-extension://{ext_id}/popup.html')
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))", msg)
    finally:
        await page.close()


async def start_recording(ctx, note: str) -> str:
    sw = await find_service_worker(ctx)
    result = await ext_call(ctx, sw, {'type': 'START_RECORDING', 'note': note})
    return (result or {}).get('id', '')


async def stop_recording(ctx) -> dict:
    sw = await find_service_worker(ctx)
    return await ext_call(ctx, sw, {'type': 'STOP_RECORDING'}) or {}


async def login_odoo(page) -> None:
    await page.goto(f"{ODOO}/web/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    if "login" in page.url:
        await page.locator("input[name='login']").fill(ODOO_USER)
        await page.locator("input[name='password']").fill(os.environ.get("ODOO_PW", ""))
        await page.locator("button[type=submit]").first.click()
        await page.wait_for_timeout(4000)


async def pick_m2o(page, placeholder: str, text: str) -> None:
    """Odoo many2one：输入搜索→点下拉结果。"""
    field = page.locator(f"input[placeholder='{placeholder}']")
    await field.fill(text)
    await page.wait_for_timeout(1200)
    opt = page.locator(".o-autocomplete--dropdown-item, ul.ui-menu li, [role='option']")
    opt = opt.filter(has_text=text.split(",")[0]).first
    await opt.click()
    await page.wait_for_timeout(800)


async def flow_create_quote(page, mark: str) -> None:
    """新建报价单（客户选已有 + 报价参考）。"""
    await page.goto(QUOTATIONS, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    await page.locator("button", has_text="New").last.click()
    await page.wait_for_timeout(3000)
    # 客户 many2one（placeholder 因语言而异——探测回退）
    for ph in ["Customer", "客户"]:
        f = page.locator(f"input[placeholder*='{ph}']")
        if await f.count():
            await pick_m2o(page, ph, "Azure")
            break
    # 报价参考
    ref = page.locator("input[name='ref']")
    if await ref.count() == 0:
        ref = page.locator("input[placeholder*='Reference'], input[placeholder*='参考']")
    if await ref.count():
        await ref.fill(f"SL-{mark}")
    await page.wait_for_timeout(1000)
    await page.locator("button[title='Save'], button:has-text('Save')").first.click()
    await page.wait_for_timeout(3000)


async def flow_confirm_quote(page, _mark: str) -> None:
    """最新报价单 → Confirm（确认成销售订单）。状态依赖：须存在草稿报价单。"""
    await page.goto(QUOTATIONS, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    row = page.locator("tr.o_data_row, .o_data_row").first
    await row.click()
    await page.wait_for_timeout(2500)
    btn = page.locator("button", has_text="Confirm")
    if await btn.count() == 0:
        btn = page.locator("button[name='action_confirm']")
    await btn.first.click()
    await page.wait_for_timeout(3000)


async def flow_create_invoice(page, _mark: str) -> None:
    """最新销售订单 → Create Invoice。状态依赖：须存在已确认订单。"""
    orders = f"{ODOO}/web#action=sale.action_orders"
    await page.goto(orders, wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    row = page.locator("tr.o_data_row, .o_data_row").first
    await row.click()
    await page.wait_for_timeout(2500)
    btn = page.locator("button", has_text="Create Invoice")
    if await btn.count() == 0:
        btn = page.locator("button[name='action_view_invoice']")
    await btn.first.click()
    await page.wait_for_timeout(3000)


FLOWS = [
    {"name": "OdooQuoteCreate", "fn": flow_create_quote},
    {"name": "OdooQuoteConfirm", "fn": flow_confirm_quote},
    {"name": "OdooInvoiceCreate", "fn": flow_create_invoice},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"s43-odoo-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await flow["fn"](page, data)
    except Exception as e:
        print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:120]}")
    await page.wait_for_timeout(1500)
    await stop_recording(ctx)
    await page.wait_for_timeout(2500)
    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.get(f"{SERVER}/api/v1/audit/sessions")
        target = [s for s in resp.json() if s["session_id"] == sid]
        if not target:
            print("  ! 会话未落库")
            return None
        print(f"  事件数: {target[0]['event_count']}")
        return sid


async def process_and_learn(token: str, sids: list[str]):
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for sid in sids:
            resp = await c.post(f"{SERVER}/api/v1/sessions/{sid}/process")
            if resp.status_code != 200:
                print(f"  process {sid[:8]}: {resp.status_code} {resp.text[:80]}")
                return None
        resp = await c.post(f"{SERVER}/api/v1/align", json={"session_ids": sids})
        if resp.status_code != 200:
            print(f"  align: {resp.status_code} {resp.text[:80]}")
            return None
        aid = resp.json()["alignment_id"]
        for attempt in range(3):
            try:
                resp = await c.post(f"{SERVER}/api/v1/alignments/{aid}/induce")
                if resp.status_code == 200:
                    break
            except Exception:
                await asyncio.sleep(5)
        else:
            print("  induce: 3 次尝试均失败")
            return None
        skill = resp.json()
        print(f"  skill: #{skill['id']} {skill['name']} ({skill['status']})")
        resp = await c.post(f"{SERVER}/api/v1/skills/{skill['id']}/assertions")
        print(f"  assertions: {resp.status_code}")
        return skill["id"]


async def main() -> None:
    print("=== S43-4：Odoo 销售链闭环（报价单→确认→创建发票）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_odoo(page)

        for flow in FLOWS:
            print(f"\n--- [{flow['name']}] ---")
            sids = []
            for rnd, mark in enumerate(["甲", "乙"]):
                data = f"{mark}{ts}"
                sid = await record_flow(token, ctx, page, flow, data)
                if sid:
                    sids.append(sid)
            if sids:
                skill_id = await process_and_learn(token, sids)
                results[flow["name"]] = skill_id
        await page.close()

    print("\n=== Odoo 销售链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "odoo-sales-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
