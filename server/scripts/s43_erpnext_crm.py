"""S43-4：ERPNext CRM 链闭环——客户→报价单→销售订单（Submit）。

ERPNext Frappe UI：列表页 Add 建新；表单字段多为 data-fieldname；
保存按钮 Save；销售订单由报价单 Create > Sales Order 转单。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_erpnext_crm.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
ERP = "http://127.0.0.1:8090"
ERP_USER = "Administrator"


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


async def login_erp(page) -> None:
    # Frappe 未保存表单离开时弹 confirm；Playwright 默认 dismiss 在 dialog
    # 已被页面关闭时抛 "No dialog is showing"，该未捕获异常会打死整个
    # Playwright node 驱动（后续所有 CDP 连接全断）——主动 accept 根治
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await page.goto(f"{ERP}/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    if "login" in page.url:
        await page.locator("input[placeholder='jane@example.com'] >> visible=true").first.fill(ERP_USER)
        await page.locator("input[placeholder='•••••']").fill("admin")
        await page.locator("button[type=submit], .btn-primary:has-text('Log')").first.click()
        await page.wait_for_timeout(4000)


async def flow_create_customer(page, mark: str) -> None:
    """建客户（Customer）。URL 直达 /new 表单（列表 Add 按钮点击
    不可靠——quick entry 弹层与 sidebar 冲突）。
    Frappe 新 desk：/app/customer/new 会重定向到 /desk/customer/new-xxx；
    名字字段 data-fieldname=customer_name（__newname 隐藏）；Save 是
    .primary-action。前置：Fiscal Year 须覆盖当天，否则 Save 被拒。"""
    await page.goto(f"{ERP}/app/customer/new", wait_until="domcontentloaded")
    await page.wait_for_timeout(4500)
    name_input = page.locator("[data-fieldname='customer_name'] input").first
    await name_input.click()
    await name_input.fill(f"SL客户{mark}")
    await page.wait_for_timeout(800)
    save = page.locator("button.primary-action:has-text('Save')").first
    await save.click()
    await page.wait_for_timeout(3500)


async def flow_create_quotation(page, mark: str) -> None:
    """建报价单（客户+明细行 item+Save）。URL 直达 /new。
    Frappe link 字段：fill 不触发搜索须 type；弹层选项是新 desk 的
    div[role=option]（非老版 awesomplete li）；Items 明细行必填——
    点行激活内联编辑（placeholder 出现），item_code 同为 link 字段。
    前置：Item 须先建（SL-STD），否则无选项可选。"""
    await page.goto(f"{ERP}/app/quotation/new", wait_until="domcontentloaded")
    await page.wait_for_timeout(4500)
    party = page.locator("[data-fieldname='party_name'] input").first
    await party.click()
    await party.type(f"SL客户{mark}", delay=250)
    await page.wait_for_timeout(2000)
    await page.locator("[data-fieldname='party_name'] [role=option]").filter(
        has_text=f"SL客户{mark}").first.click(timeout=8000)
    await page.wait_for_timeout(1500)
    # 明细行：点行激活内联编辑，再选 item
    await page.locator(".grid-row [data-fieldname='item_code']").first.click()
    await page.wait_for_timeout(1500)
    ic = page.get_by_placeholder("Item Code")
    await ic.click()
    await ic.type("SL-STD", delay=120)
    await page.wait_for_timeout(2000)
    await page.locator("[role=option]").filter(has_text="SL-STD").first.click(timeout=8000)
    await page.wait_for_timeout(2000)
    save = page.locator("button.primary-action:has-text('Save')").first
    await save.click()
    await page.wait_for_timeout(4000)
    # ERPNext 业务规则：草稿报价单不能转 SO（search_widget 过滤
    # docstatus=1）——Save 后须 Submit（Submit→Yes 确认）
    submit = page.locator("button.primary-action:has-text('Submit')").first
    await submit.click(timeout=8000)
    await page.wait_for_timeout(2000)
    await page.locator("button:has-text('Yes')").first.click()
    await page.wait_for_timeout(4000)


async def flow_create_so(page, mark: str) -> None:
    """销售订单：每轮先建+提交一张新报价单（业务约束：一张已提交报价单
    只能转一张 SO，两轮录制须两张）→ /app/sales-order/new → Get Items
    From > Quotation（搜该单号，明细+客户自动带入）→ Save → Submit。"""
    # 建一张本轮专用报价单（复用报价单流程，客户用当轮 mark 唯一前缀）
    await flow_create_quotation(page, mark)
    await page.goto(f"{ERP}/app/sales-order/new", wait_until="domcontentloaded")
    await page.wait_for_timeout(5000)
    await page.locator("button").filter(has_text="Get Items From").first.click()
    await page.wait_for_timeout(1500)
    await page.locator("[role=menuitem], .dropdown-item").filter(
        has_text="Quotation").first.click()
    await page.wait_for_timeout(2500)
    si = page.locator("[data-fieldname='search_term'] input").first
    if await si.count() == 0:
        si = page.locator("[data-fieldname='search_term']").first
    await si.click()
    # 搜索词=最新已提交报价单完整单号——"SAL" 前缀在单据积累后分页
    # 挤掉目标行（S43-4 实测 00021 被 37+ 挤出首页），完整单号唯一命中
    import subprocess as _sp
    out = _sp.run(
        ["docker", "exec", "erpnext-backend-1", "sh", "-c",
         "cd /home/frappe/frappe-bench && bench --site frontend execute "
         "frappe.client.get_list --kwargs "
         "\"{'doctype':'Quotation','filters':[['docstatus','=',1]],"
         "'order_by':'creation desc','limit_page_length':1,'fields':['name']}\""],
        capture_output=True, text=True, timeout=90).stdout.strip()
    search_term = out.split('"name": "')[-1].split('"')[0] if '"name"' in out else "SAL"
    await si.type(search_term, delay=150)
    # 等结果行渲染（search_widget 有 ~2s 延迟），勾选命中行 + Get Items
    target = page.locator("[data-fieldname='results_area'] .list-item").filter(
        has_text=search_term)
    await target.first.wait_for(state="visible", timeout=15000)
    await target.first.locator("input[type=checkbox]").check()
    await page.wait_for_timeout(800)
    # 精确匹配：has_text 会连主表单 "Get Items From"（DOM 在前）一起
    # 命中且 .first 抢先——被 modal 遮挡超时
    await page.locator("button", has_text="Get Items").filter(
        has_not_text="From").first.click()
    await page.wait_for_timeout(4000)
    # 报价单无 delivery_date，映射后行内必填缺失——Get Items 映射完成
    # 后 Frappe 自动展开 row-form 行编辑，直接补值（不再点 grid 单元格：
    # 明细已预填时点单元格反而收起编辑器，且多行同名字段 ordinal 歧义）
    # Get Items 映射不自动展开行编辑——单击 item_code 单元格展开
    # （实测有效：DD placeholder 与 Item Code/Rate 输入同时出现）
    await page.locator(
        ".grid-row [data-fieldname='item_code']").first.click()
    await page.wait_for_timeout(1500)
    dd = page.get_by_placeholder("Delivery Date")
    await dd.first.click()
    await dd.first.fill("2026-10-15")
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1000)
    save = page.locator("button.primary-action:has-text('Save')").first
    await save.click()
    await page.wait_for_timeout(5000)
    submit = page.locator("button.primary-action:has-text('Submit')").first
    await submit.click(timeout=8000)
    await page.wait_for_timeout(2000)
    await page.locator("button:has-text('Yes')").first.click()
    await page.wait_for_timeout(4000)


FLOWS = [
    {"name": "ErpCustomerCreate", "fn": flow_create_customer},
    {"name": "ErpQuotationCreate", "fn": flow_create_quotation},
    {"name": "ErpSalesOrderCreate", "fn": flow_create_so},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"s43-erp-{flow['name']}")
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
    print("=== S43-4：ERPNext CRM 链闭环（客户→报价单→销售订单）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_erp(page)

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

    print("\n=== ERPNext CRM 链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "erpnext-crm-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
