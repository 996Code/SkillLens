"""S34 块 2：Odoo（本地 Docker 开源 ERP）多目标全链路验证。

在 Odoo 17 Contacts 上录制 CRUD 流程（经 9222 常驻浏览器 + 插件采集），
走 process → align → induce → assertions 学习管道——验证语义定位/学习/回放
在 njmind 之外的第二个真实 ERP 上的泛化能力。

流程（各录 2 轮，换数据）：
- CreateContact：New → 填 Name → Save
- SearchContact：搜索框输入 → 回车
- UpdateContact：打开卡片 → Edit → 改 Name → Save

用法：cd server && uv run python ../scripts/s34_odoo_record.py
前提：Odoo 栈在 8069（deploy/odoo）；server 在 8710；live_browser 在 9222。
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
ODOO = "http://127.0.0.1:8069"
ODOO_LOGIN = "admin@local.test"
ODOO_PASSWORD = "odoo-admin-local"

NAME_PH = "e.g. Lumber Inc"


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
    result = await ext_call(ctx, sw, {'type': 'START_RECORDING', 'note': note})
    return (result or {}).get('id', '')


async def stop_recording(ctx) -> dict:
    sw = await find_service_worker(ctx)
    return await ext_call(ctx, sw, {'type': 'STOP_RECORDING'}) or {}


async def goto_contacts(page) -> None:
    await page.goto(f"{ODOO}/web#action=134")
    # hash-only goto 不触发整页加载（SPA 停在旧视图）——强制 reload 保证回到看板
    await page.reload()
    await page.wait_for_timeout(3000)


async def flow_create(page, name: str) -> None:
    # 节奏模拟真实用户：动作间 >2.5s 停顿（超 IDLE_MS 2s），
    # 让 input 成为独立窗口锚点（否则被吞进上一窗，回放不会填值）
    await page.locator("button.o-kanban-button-new >> visible=true").click()
    await page.wait_for_timeout(3000)
    await page.locator(f"input[placeholder='{NAME_PH}']").fill(name)
    await page.wait_for_timeout(3000)
    await page.locator("button.o_form_button_save >> visible=true").click()
    await page.wait_for_timeout(2500)


async def flow_search(page, keyword: str) -> None:
    box = page.locator("input[placeholder='Search...'] >> visible=true").first
    await box.fill(keyword)
    await box.press("Enter")
    await page.wait_for_timeout(2500)


async def flow_update(page, new_name: str) -> None:
    # 打开第一张卡片
    await page.locator(".o_kanban_record >> visible=true").first.click()
    await page.wait_for_timeout(2000)
    await page.locator("button.o_form_button_edit >> visible=true").click()
    await page.wait_for_timeout(1500)
    await page.locator(f"input[placeholder='{NAME_PH}']").fill(new_name)
    await page.wait_for_timeout(800)
    await page.locator("button.o_form_button_save >> visible=true").click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "OdooCreateContact", "fn": flow_create,
     "datas": ["Odoo Contact A1", "Odoo Contact A2"]},
    {"name": "OdooSearchContact", "fn": flow_search,
     "datas": ["Odoo Contact", "Contact A"]},
    {"name": "OdooUpdateContact", "fn": flow_update,
     "datas": ["Odoo Contact A1-upd", "Odoo Contact A2-upd"]},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（数据: {data[:30]}）")
    sid = await start_recording(ctx, f"odoo-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await goto_contacts(page)
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
        print(f"  事件数: {target[0]['event_count']} 语义: {target[0]['semantic_action_count']}")
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
    print("=== S34 块 2：Odoo 多目标全链路验证 ===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        # 常驻浏览器登录 Odoo（回放也在此浏览器，登录态共享）
        await page.goto(f"{ODOO}/web/login")
        await page.locator("input[name='login']").fill(ODOO_LOGIN)
        await page.locator("input[name='password']").fill(ODOO_PASSWORD)
        await page.locator("button[type='submit']").click()
        await page.wait_for_timeout(4000)
        print(f"Odoo 登录: {page.url}")

        for flow in FLOWS:
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
            results.append({"flow": flow["name"], "skill_id": skill_id,
                            "sessions": [s[:8] for s in sids]})

        print("\n=== Odoo 录制学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']} (sessions: {r['sessions']})")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint34"
        out.mkdir(parents=True, exist_ok=True)
        (out / "odoo-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已存 demo/sprint34/odoo-skills.json")

        await page.close()
        await browser.close()


asyncio.run(main())
