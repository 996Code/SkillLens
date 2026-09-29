"""S35：Dolibarr（本地 Docker，PHP 经典多页 ERP）全面模拟。

与 Odoo（SPA）架构互补的第三类目标：每次操作整页加载（navigation 事件丰富）。
流程（各 2 轮换数据，>2.5s 真实用户节奏）：
- DoliCreateThirdParty：新建第三方（name + phone）
- DoliCreateProduct：新建产品（ref + label）
- DoliSearchThirdParty：列表页搜索（表单提交）
- DoliUpdateThirdParty：打开记录改名保存（数据依赖锚点——诚实测试）

用法：cd server && uv run python ../scripts/s35_doli_full.py [flow,...]
前提：Dolibarr 栈 8080；server 8710；live_browser 9222。
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
DOLI = "http://127.0.0.1:8080"
DOLI_LOGIN = "admin"
DOLI_PASSWORD = "doli-admin-local"


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


async def doli_login(page) -> None:
    await page.goto(f"{DOLI}/")
    await page.wait_for_timeout(1500)
    if await page.locator("input[name='username'], #username").count():
        await page.locator("input[name='username'], #username").first.fill(DOLI_LOGIN)
        await page.locator("input[name='password'], #password").first.fill(DOLI_PASSWORD)
        await page.locator("button[type='submit'], input[type='submit']").first.click()
        await page.wait_for_timeout(2500)


async def flow_create_third(page, data: str) -> None:
    name, phone = data.split("|")
    await page.goto(f"{DOLI}/societe/card.php?action=create")
    await page.wait_for_timeout(2500)
    await page.locator("input[name='name']").fill(name)
    await page.wait_for_timeout(2500)
    await page.locator("input[name='phone']").fill(phone)
    await page.wait_for_timeout(2500)
    await page.locator("input[name='save']").click()
    await page.wait_for_timeout(2500)


async def flow_create_product(page, data: str) -> None:
    ref, label = data.split("|")
    await page.goto(f"{DOLI}/product/card.php?action=create")
    await page.wait_for_timeout(2500)
    await page.locator("input[name='ref']").fill(ref)
    await page.wait_for_timeout(2500)
    await page.locator("input[name='label']").fill(label)
    await page.wait_for_timeout(2500)
    await page.locator("input[name='add']").click()
    await page.wait_for_timeout(2500)


async def flow_search_third(page, keyword: str) -> None:
    await page.goto(f"{DOLI}/societe/list.php")
    await page.wait_for_timeout(2500)
    await page.locator("input[name='search_nom']").fill(keyword)
    await page.wait_for_timeout(2500)
    await page.locator("button[name='button_search_x']").click()
    await page.wait_for_timeout(2500)


async def flow_update_third(page, new_name: str) -> None:
    await page.goto(f"{DOLI}/societe/list.php")
    await page.wait_for_timeout(2500)
    # 打开第一行记录（数据依赖锚点——诚实测试）
    await page.locator("tr.oddeven td a >> visible=true").first.click()
    await page.wait_for_timeout(2500)
    # 编辑模式（href 含 action=edit，语言无关；可见过滤避开隐藏的 edit* 链接）
    edit = page.locator("a.butAction[href*='action=edit'], a[href*='action=edit'] >> visible=true")
    if await edit.count():
        await edit.first.click()
        await page.wait_for_timeout(2500)
    await page.locator("input[name='name']").fill(new_name)
    await page.wait_for_timeout(2500)
    await page.locator("input[name='save']").click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "DoliCreateThirdParty", "fn": flow_create_third,
     "datas": ["Doli Third E1|0555-0201", "Doli Third E2|0555-0202"]},
    {"name": "DoliCreateProduct", "fn": flow_create_product,
     "datas": ["DOLI-P01|Doli Product One", "DOLI-P02|Doli Product Two"]},
    {"name": "DoliSearchThirdParty", "fn": flow_search_third,
     "datas": ["Doli Third", "E2"]},
    {"name": "DoliUpdateThirdParty", "fn": flow_update_third,
     "datas": ["Doli Third E1-upd", "Doli Third E2-upd"]},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（数据: {data[:40]}）")
    sid = await start_recording(ctx, f"doli35-{flow['name']}")
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


async def main() -> None:
    print("=== S35：Dolibarr 全面模拟（多流程 CRUD） ===")
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await doli_login(page)
        print(f"Dolibarr 登录: {page.url}")

        for flow in FLOWS:
            if only and flow["name"] not in only:
                continue
            print(f"\n--- 流程 [{flow['name']}] ---")
            sids = []
            for data in flow["datas"]:
                sid = await record_flow(token, ctx, page, flow, data)
                if sid:
                    sids.append(sid)
            if len(sids) < 2:
                print("  ! 会话不足 2 个，跳过学习")
                continue
            skill_id = await process_and_learn(token, sids)
            results.append({"flow": flow["name"], "skill_id": skill_id})

        print("\n=== S35 Dolibarr 多流程结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint35"
        out.mkdir(parents=True, exist_ok=True)
        (out / "doli-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        await page.close()
        await browser.close()


asyncio.run(main())
