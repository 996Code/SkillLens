"""S43-4：JeecG 在线表单链闭环——建表→同步数据库→功能测试填单。

流程（每轮独立表名，录 2 轮学习）：
1. OnlineFormCreate：/online/cgform 新增（表名 ASCII+表描述）→保存
   （默认 6 系统字段足够，自定义字段区按钮在隐藏容器不可点）
2. OnlineFormSync：列表行→更多→同步数据库→开始同步（状态 未同步→已同步）
3. OnlineFormFill：更多→功能测试（新 tab 列表页）→新增→确定
   （POST /online/cgform/api/form/{code} 写请求=确定性证据）

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_jeecg_form.py
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
JEECG = "http://127.0.0.1:8095"


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


async def ensure_login(page) -> None:
    await page.goto(JEECG, wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)
    if "login" in page.url.lower():
        await page.get_by_placeholder("请输入账号").fill("admin")
        await page.get_by_placeholder("请输入密码").fill("123456")
        await page.locator("button, .ant-btn").filter(has_text="登").first.click()
        await page.wait_for_timeout(5000)


async def flow_form_create(page, mark: str) -> None:
    """建在线表单：列表→新增→表名/表描述→保存（默认字段足够）。"""
    await page.goto(f"{JEECG}/online/cgform", wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)
    await page.locator("button").filter(has_text="新增").first.click()
    await page.wait_for_timeout(2500)
    drawer = page.locator(".ant-drawer-content, .ant-modal")
    # 表名=抽屉第一个文本输入（label 同行 has_text 会误命中嵌套容器，
    # 实测按序填充；表名须 ASCII——中文被"表名不允许输入中文"拦）
    await drawer.locator("input[type=text]").nth(0).click()
    await drawer.locator("input[type=text]").nth(0).fill(f"sl_form_{mark}")
    await page.wait_for_timeout(300)
    await drawer.locator("input[type=text]").nth(1).click()
    await drawer.locator("input[type=text]").nth(1).fill(f"SL表单{mark}")
    await page.wait_for_timeout(500)
    save = drawer.locator("button").filter(has_text="保存").last
    await save.click()
    await page.wait_for_timeout(3000)


async def _close_extra_tabs(ctx, keep) -> None:
    for pg in list(ctx.pages):
        if pg is not keep:
            try:
                await pg.close()
            except Exception:
                pass


async def flow_form_sync(page, mark: str) -> None:
    """同步数据库：行→更多→同步数据库→开始同步（发布）。"""
    await page.goto(f"{JEECG}/online/cgform", wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)
    row = page.locator(".ant-table-row").filter(has_text=f"sl_form_{mark}").first
    await row.get_by_text("更多").first.click()
    await page.wait_for_timeout(1200)
    await page.locator(".ant-dropdown-menu-item, [class*=dropdown-menu] li").filter(
        has_text="同步数据库").first.click()
    await page.wait_for_timeout(1500)
    ok = page.locator(".ant-modal-confirm .ant-btn-primary, .ant-modal .ant-btn-primary").first
    if await ok.count():
        await ok.click()
    await page.wait_for_timeout(3500)


async def flow_form_fill(page, mark: str) -> None:
    """功能测试填单：更多→功能测试（新 tab）→新增→确定（POST 写证据）。"""
    await page.goto(f"{JEECG}/online/cgform", wait_until="domcontentloaded")
    await page.wait_for_timeout(4000)
    row = page.locator(".ant-table-row").filter(has_text=f"sl_form_{mark}").first
    await row.get_by_text("更多").first.click()
    await page.wait_for_timeout(1200)
    await page.locator(".ant-dropdown-menu-item, [class*=dropdown-menu] li").filter(
        has_text="功能测试").first.click()
    await page.wait_for_timeout(4000)
    # 功能测试开新 tab
    target = page
    if len(page.context.pages) > 1:
        target = page.context.pages[-1]
        await target.wait_for_timeout(3000)
    await target.locator("button").filter(has_text="新增").first.click()
    await target.wait_for_timeout(2000)
    ok = target.locator(".ant-modal .ant-btn-primary, .ant-modal button").filter(
        has_text="确定").first
    if await ok.count():
        await ok.click()
    await target.wait_for_timeout(3000)
    # 关功能测试 tab 回列表（状态复位）
    if target is not page:
        try:
            await target.close()
        except Exception:
            pass


FLOWS = [
    {"name": "OnlineFormCreate", "fn": flow_form_create},
    {"name": "OnlineFormSync", "fn": flow_form_sync},
    {"name": "OnlineFormFill", "fn": flow_form_fill},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    await ensure_login(page)
    sid = await start_recording(ctx, f"s43-jeecg-form-{flow['name']}")
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
    print("=== S43-4：JeecG 在线表单链闭环（建表→同步→功能测试填单）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

        for flow in FLOWS:
            print(f"\n--- [{flow['name']}] ---")
            sids = []
            for rnd, mark in enumerate(["a", "b"]):
                data = f"{mark}{ts}"
                sid = await record_flow(token, ctx, page, flow, data)
                if sid:
                    sids.append(sid)
            if sids:
                skill_id = await process_and_learn(token, sids)
                results[flow["name"]] = skill_id
        await page.close()

    print("\n=== JeecG 在线表单链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "jeecg-form-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
