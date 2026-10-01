"""S43-4：Dolibarr 订单链闭环——第三方→客户订单→确认→开票。

经典 PHP 表单（非 SPA）：直接 URL 表单、原生 input/select、提交按钮
type=submit。核心链走 commandes（客户订单）。

用法：cd server && DOLI_PW=... PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_doli_order.py
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
DOLI = "http://127.0.0.1:8080"
DOLI_USER = "admin"


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


async def login_doli(page) -> None:
    await page.goto(f"{DOLI}/", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    if "login" in page.url.lower() or await page.locator("#username").count():
        await page.locator("input[name='username'], #username").first.fill(DOLI_USER)
        await page.locator("input[name='password'], #password").first.fill(
            os.environ.get("DOLI_PW", ""))
        await page.locator("input[type='submit'], button[type=submit]").first.click()
        await page.wait_for_timeout(3000)


def latest_third_id() -> int:
    """最新第三方 id（订单须有客户）。"""
    import subprocess
    r = subprocess.run(
        ["docker", "exec", "dolibarr-db-1", "sh", "-c",
         "mariadb -udolibarr -p$(printenv MARIADB_PASSWORD) dolibarr -N -e "
         "'select rowid from llx_societe order by rowid desc limit 1' 2>/dev/null"],
        capture_output=True, text=True, timeout=30)
    out = (r.stdout or "").strip().splitlines()
    return int(out[0]) if out and out[0].isdigit() else 0


async def flow_create_third(page, mark: str) -> None:
    """新建第三方（客户）。"""
    await page.goto(f"{DOLI}/societe/card.php?action=create", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    name = page.locator("input[name='name']")
    await name.fill(f"闭环客户{mark}")
    await page.wait_for_timeout(800)
    # 客户类型选 Customer/Client（第一个 client radio/checkbox）
    try:
        cust = page.locator("input[name='typent_id']")
        if await cust.count():
            pass  # 下拉有默认
    except Exception:
        pass
    await page.locator("button[type=submit], input[type=submit]").first.click()
    await page.wait_for_timeout(3500)


async def flow_create_order(page, mark: str) -> None:
    """为客户建订单（第三方刚建的；Dolibarr 表单须先选客户再跳订单表单）。"""
    sid = latest_third_id()
    if sid == 0:
        print("  ! 无第三方可下订单")
        return
    # 直接带 socid 进订单创建表单
    await page.goto(f"{DOLI}/commande/card.php?action=create&socid={sid}",
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    ref = page.locator("input[name='ref_customer'], input[name='ref']")
    if await ref.count():
        await ref.first.fill(f"SL-ORD-{mark}")
    # 加一行产品（description+qty+price 手工行）
    desc = page.locator("textarea[name='dp_desc'], #dp_desc")
    if await desc.count():
        await desc.first.fill("测试服务行")
    qty = page.locator("input[name='qty1']")
    if await qty.count():
        await qty.fill("2")
    price = page.locator("input[name='price_ht']")
    if await price.count():
        await price.first.fill("100")
    await page.locator("button[type=submit], input[type=submit]").first.click()
    await page.wait_for_timeout(3500)


async def flow_validate_order(page, _mark: str) -> None:
    """最新草稿订单 → 确认（Validate）。状态依赖：须 draft 订单。"""
    await page.goto(f"{DOLI}/commande/list.php?search_status=0",
                    wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    # 行操作：确认图标（title 含 确认/Validate）
    btn = page.locator("a[title*='确认'], a[title*='Validate'], a[href*='validate']").first
    await btn.click()
    await page.wait_for_timeout(2500)
    # 确认弹页的 Yes/确认
    confirm = page.locator("input[value='Yes'], button:has-text('确认'), input[type=submit]").first
    try:
        if await confirm.count():
            await confirm.click()
            await page.wait_for_timeout(3000)
    except Exception:
        pass


async def flow_create_invoice(page, _mark: str) -> None:
    """最新已确认订单 → 生成发票（从订单页 Create Invoice）。"""
    await page.goto(f"{DOLI}/commande/list.php", wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)
    # 点第一行进订单详情
    row_link = page.locator("table tbody tr a[href*='commande/card.php']").first
    await row_link.click()
    await page.wait_for_timeout(2500)
    btn = page.locator("a[title*='发票'], a[title*='Invoice'], a[href*='facture']").first
    await btn.click()
    await page.wait_for_timeout(3000)


FLOWS = [
    {"name": "DoliThirdCreate", "fn": flow_create_third},
    {"name": "DoliOrderCreate", "fn": flow_create_order},
    {"name": "DoliOrderValidate", "fn": flow_validate_order},
    {"name": "DoliInvoiceCreate", "fn": flow_create_invoice},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"s43-doli-{flow['name']}")
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
    print("=== S43-4：Dolibarr 订单链闭环（第三方→订单→确认→开票）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_doli(page)

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

    print("\n=== Dolibarr 订单链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "dolibarr-order-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
