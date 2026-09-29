"""S35：Odoo 全面模拟（多流程 CRUD + 多菜单 + 多记录类型）。

在 Odoo 17 Contacts 上录制 4 类流程（各 2 轮换数据，>2.5s 真实用户节奏）：
- OdooUpdateContact：列表 → 打开记录 → 改名 → Save
- OdooDeleteContact：列表 → 勾选 → Action → Delete → 确认
- OdooCreateContactRich：New → 名字 + 电话 → Save（多输入变量）
- OdooCreateTag：Configuration → Contact Tags → New → 命名 → Save（跨菜单）

用法：cd server && uv run python ../scripts/s35_odoo_full.py [flow1,flow2,...]
前提：Odoo 栈 8069；server 8710；live_browser 9222。
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
ODOO = "http://127.0.0.1:8069"
ODOO_LOGIN = "admin@local.test"
ODOO_PASSWORD = "odoo-admin-local"

NAME_NEW = "e.g. Lumber Inc"      # 新建表单（公司型默认）
NAME_EDIT = "e.g. Brandom Freeman"  # 既有记录表单（个人型）


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


async def goto_list(page) -> None:
    await page.goto(f"{ODOO}/web#action=134&view_type=list")
    await page.reload()
    await page.wait_for_timeout(3000)


async def goto_kanban(page) -> None:
    await page.goto(f"{ODOO}/web#action=134")
    await page.reload()
    await page.wait_for_timeout(3000)


async def flow_update(page, new_name: str) -> None:
    await goto_list(page)
    await page.locator(".o_data_row .o_data_cell").first.click()
    await page.wait_for_timeout(3000)
    await page.locator(f"input[placeholder='{NAME_EDIT}']").fill(new_name)
    await page.wait_for_timeout(3000)
    await page.locator("button.o_form_button_save >> visible=true").click()
    await page.wait_for_timeout(2500)


async def flow_delete(page, _: str) -> None:
    await goto_list(page)
    await page.locator(".o_list_record_selector input").first.click()
    await page.wait_for_timeout(2500)
    await page.locator("button.o_dropdown_title, .o_cp_action_menus button").first.click()
    await page.wait_for_timeout(2500)
    await page.locator(
        ".dropdown-item:has-text('Delete'), .o_menu_item:has-text('Delete')").first.click()
    await page.wait_for_timeout(2500)
    await page.locator(".modal button:has-text('Delete')").last.click()
    await page.wait_for_timeout(2500)


async def flow_create_rich(page, data: str) -> None:
    name, phone = data.split("|")
    await goto_kanban(page)
    await page.locator("button.o-kanban-button-new >> visible=true").click()
    await page.wait_for_timeout(3000)
    await page.locator(f"input[placeholder='{NAME_NEW}']").fill(name)
    await page.wait_for_timeout(3000)
    try:
        await page.locator("input[placeholder='Phone']").fill(phone)
    except Exception:
        pass  # 电话字段不可见时跳过（多输入变量 fail-open）
    await page.wait_for_timeout(3000)
    await page.locator("button.o_form_button_save >> visible=true").click()
    await page.wait_for_timeout(2500)


async def flow_create_tag(page, tag: str) -> None:
    await goto_kanban(page)
    await page.locator("button:has-text('Configuration')").first.click()
    await page.wait_for_timeout(2500)
    await page.locator(".dropdown-item:has-text('Contact Tags'), a:has-text('Contact Tags')").first.click()
    await page.wait_for_timeout(3000)
    await page.locator("button.o-kanban-button-new, button.o_list_button_add >> visible=true").first.click()
    await page.wait_for_timeout(3000)
    # 标签名输入框：Name 字段
    await page.locator("input[name='name'], input[placeholder='e.g. Customer']").first.fill(tag)
    await page.wait_for_timeout(3000)
    await page.locator("button.o_form_button_save >> visible=true").click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "OdooUpdateContact", "fn": flow_update,
     "datas": ["Odoo Contact B1-renamed", "Odoo Contact B2-renamed"]},
    {"name": "OdooDeleteContact", "fn": flow_delete, "datas": ["", ""]},
    {"name": "OdooCreateContactRich", "fn": flow_create_rich,
     "datas": ["Odoo Rich C1|0555-0101", "Odoo Rich C2|0555-0102"]},
    {"name": "OdooCreateTag", "fn": flow_create_tag,
     "datas": ["S35 Tag One", "S35 Tag Two"]},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（数据: {data[:40]}）")
    sid = await start_recording(ctx, f"odoo35-{flow['name']}")
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
    print("=== S35：Odoo 全面模拟（多流程 CRUD） ===")
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else None
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await page.goto(f"{ODOO}/web/login")
        await page.locator("input[name='login']").fill(ODOO_LOGIN)
        await page.locator("input[name='password']").fill(ODOO_PASSWORD)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(4000)
        print(f"Odoo 登录: {page.url}")

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

        print("\n=== S35 Odoo 多流程结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint35"
        out.mkdir(parents=True, exist_ok=True)
        (out / "odoo-full-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        await page.close()
        await browser.close()


asyncio.run(main())
