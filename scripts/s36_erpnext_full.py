"""S36：ERPNext（Frappe，开源 ERP 第二极）多目标全链路验证。

流程（各 2 轮换数据，>2.5s 真实用户节奏）：
- ErpCreateCustomer：/app/customer → Add Customer → customer_name → Save
- ErpCreateLead：/app/lead → Add Lead → lead_name → Save

用法：cd server && uv run python ../scripts/s36_erpnext_full.py [flow,...]
前提：ERPNext 栈 8090（deploy/erpnext，已过安装向导）；server 8710；live_browser 9222。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
ERP = "http://127.0.0.1:8090"
ERP_USER = "Administrator"
ERP_PASSWORD = "admin"


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
    for w in ctx.service_workers:
        if 'service-worker-loader' in w.url or 'uploader' in w.url:
            return w
    raise RuntimeError('extension service worker 未找到')


async def ext_call(ctx, sw, msg: dict) -> object:
    ext_id = sw.url.split('/')[2]
    page = await ctx.new_page()
    try:
        await page.goto(f'chrome-extension://{ext_id}/popup.html')
        return await page.evaluate(
            """(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))""",
            msg)
    finally:
        await page.close()


async def start_recording(ctx, note: str) -> str:
    sw = await find_service_worker(ctx)
    return (await ext_call(ctx, sw, {'type': 'START_RECORDING', 'note': note}) or {}).get('id', '')


async def stop_recording(ctx) -> dict:
    sw = await find_service_worker(ctx)
    return await ext_call(ctx, sw, {'type': 'STOP_RECORDING'}) or {}


async def erp_login(page) -> None:
    await page.goto(f"{ERP}/", wait_until="domcontentloaded")
    try:
        await page.wait_for_selector(
            "input[placeholder='jane@example.com'] >> visible=true", timeout=8000)
    except Exception:
        return  # profile 已带会话（desk 直达），免登录
    await page.locator("input[placeholder='jane@example.com'] >> visible=true").first.fill(ERP_USER)
    await page.locator("input[placeholder='•••••']").fill(ERP_PASSWORD)
    await page.locator(".btn-login, button:has-text('Log in')").first.click()
    await page.wait_for_timeout(8000)


async def flow_create_customer(page, name: str) -> None:
    await page.goto(f"{ERP}/app/customer", wait_until="domcontentloaded")
    await page.wait_for_selector("button:has-text('Add Customer')", timeout=60000)
    await page.wait_for_timeout(3000)
    await page.locator("button:has-text('Add Customer')").click()
    await page.wait_for_selector(".modal.show input[data-fieldname='customer_name']",
                                 timeout=30000)
    await page.wait_for_timeout(3000)
    # fill 必须限定模态内：背景列表过滤框同 fieldname 且 DOM 序在前
    await page.locator(".modal.show input[data-fieldname='customer_name']").fill(name)
    await page.wait_for_timeout(3000)
    await page.locator(".modal.show button:has-text('Save')").first.click()
    await page.wait_for_timeout(3000)


async def flow_create_lead(page, name: str) -> None:
    await page.goto(f"{ERP}/app/lead", wait_until="domcontentloaded")
    await page.wait_for_selector(
        "button:has-text('Add Lead'), button:has-text('New Lead')", timeout=60000)
    await page.wait_for_timeout(3000)
    add = page.locator("button:has-text('Add Lead'), button:has-text('New Lead')")
    if await add.count():
        await add.first.click()
        await page.wait_for_timeout(3000)
    # Lead 是整页表单（非快速新建模态）
    modal = page.locator(".modal.show input[data-fieldname='first_name']")
    if await modal.count():
        await modal.fill(name)
        await page.wait_for_timeout(3000)
        await page.locator(".modal.show button:has-text('Save')").first.click()
    else:
        await page.locator("input[data-fieldname='first_name']").first.fill(name)
        await page.wait_for_timeout(3000)
        await page.locator("button:has-text('Save') >> visible=true").first.click()
    await page.wait_for_timeout(3000)


FLOWS = [
    {"name": "ErpCreateCustomer", "fn": flow_create_customer,
     "datas": ["ErpNext Cust H1", "ErpNext Cust H2"]},
    {"name": "ErpCreateLead", "fn": flow_create_lead,
     "datas": ["ErpNext Lead I1", "ErpNext Lead I2"]},
]


async def record_round(token: str, flow, data: str) -> str | None:
    """单轮录制：独立 playwright 连接（规避 Playwright node driver 在
    ERPNext 页面上因未处理 Promise rejection 崩溃——triggerUncaughtException
    导致 driver 进程退出，"Connection closed while reading from the driver"；
    每轮新连接，崩溃只损失当轮，可重试）。"""
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        try:
            ctx = browser.contexts[0]
            print(f"  录制 {flow['name']}（数据: {data[:40]}）")
            sid = await start_recording(ctx, f"erp36-{flow['name']}")
            if not sid:
                print("  ! 无法开始录制")
                return None
            page = await ctx.new_page()
            try:
                await flow["fn"](page, data)
            except Exception as e:
                print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:120]}")
            await asyncio.sleep(1.5)
            await stop_recording(ctx)
            await asyncio.sleep(2.5)
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.get(f"{SERVER}/api/v1/audit/sessions")
        target = [s for s in resp.json() if s["session_id"] == sid]
        if not target:
            print("  ! 会话未落库")
            return None
        print(f"  事件数: {target[0]['event_count']}")
        return sid


async def main() -> None:
    print("=== S36：ERPNext 多目标验证 ===")
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    token = mint_token()
    results = []
    for flow in FLOWS:
        if only and flow["name"] not in only:
            continue
        print(f"\n--- 流程 [{flow['name']}] ---")
        sids = []
        for data in flow["datas"]:
            sid = await record_round(token, flow, data)
            if sid:
                sids.append(sid)
        if len(sids) < 2:
            print("  ! 会话不足 2 个，跳过学习")
            continue
        skill_id = await process_and_learn(token, sids)
        results.append({"flow": flow["name"], "skill_id": skill_id})

    print("\n=== S36 ERPNext 结果 ===")
    for r in results:
        print(f"  {r['flow']}: skill #{r['skill_id']}")
    out = Path(__file__).resolve().parent.parent / "demo" / "sprint36"
    out.mkdir(parents=True, exist_ok=True)
    (out / "erpnext-skills.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")




async def process_and_learn(token: str, sids: list[str]):
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for sid in sids:
            resp = await c.post(f"{SERVER}/api/v1/sessions/{sid}/process")
            if resp.status_code != 200:
                print(f"  process {sid[:8]}: {resp.status_code} {resp.text[:100]}")
                return None
        resp = await c.post(f"{SERVER}/api/v1/align", json={"session_ids": sids})
        if resp.status_code != 200:
            print(f"  align: {resp.status_code} {resp.text[:100]}")
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


asyncio.run(main())
