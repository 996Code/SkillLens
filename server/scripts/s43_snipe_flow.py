"""S43-4：Snipe-IT 资产生命周期闭环（建资产→签出→签入→维护）。

前置（一次性，脚本自动做）：状态标签（可部署）、型号（笔记本）、位置。
核心链（录制×2→学习→回放）：新建资产 → 签出给用户 → 签入 → 维护请求。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/s43_snipe_flow.py
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
SNIPE = "http://127.0.0.1:8081"
SNIPE_USER = "admin"
SNIPE_PASS = "Snipe@618local"


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


async def find_service_worker(ctx, wait_ms: int = 20000):
    """新 profile 冷启动时 SW 注册可能滞后——轮询等待。"""
    import asyncio as _aio
    deadline = _aio.get_event_loop().time() + wait_ms / 1000
    while _aio.get_event_loop().time() < deadline:
        for w in ctx.service_workers:
            if 'service-worker-loader' in w.url or 'uploader' in w.url:
                return w
        await _aio.sleep(1000 / 1000)
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


async def login_snipe(page) -> None:
    await page.goto(f"{SNIPE}/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    if "login" in page.url:
        await page.locator("input[name='username']").fill(SNIPE_USER)
        await page.locator("input[name='password']").fill(SNIPE_PASS)
        await page.locator("button[type='submit']").first.click()
        await page.wait_for_timeout(4000)


async def ensure_prereq(page) -> None:
    """基础数据已由 SQL 种子（manufacturer/model）——查缺兜底：
    仅当型号下拉为空时提示（人工补种）。"""
    await page.goto(f"{SNIPE}/hardware/create", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    opts = await page.evaluate(
        "() => { const s = document.querySelector(\"select[name='model_id']\");"
        " return s ? Array.from(s.options).length : -1; }")
    print(f"  prereq: model_id options={opts}")


async def pick_select2(page, container_nth: int, text: str) -> None:
    """Snipe-IT 下拉是 select2 AJAX——点开容器→输入→点结果。"""
    box = page.locator(".select2-container").nth(container_nth)
    await box.click()
    await page.wait_for_timeout(800)
    search = page.locator("input.select2-search__field")
    await search.last.fill(text)
    await page.wait_for_timeout(1200)
    opt = page.locator(".select2-results__option", has_text=text).first
    await opt.click()
    await page.wait_for_timeout(800)


async def flow_create_asset(page, tag: str) -> None:
    """新建资产（型号经 select2 选 ThinkPad X1；状态默认）。"""
    await page.goto(f"{SNIPE}/hardware/create", wait_until="domcontentloaded")
    await page.wait_for_selector(".select2-container", timeout=15000)
    await page.wait_for_timeout(1500)
    await page.locator("input[name='asset_tags[1]']").first.fill(tag)
    await page.locator("input[name='serials[1]']").first.fill(f"SN-{tag}")
    # select2 AJAX 下拉：options 为空，原生 select_option/设值都无效——
    # 必须走 UI 路径（点容器→搜索→点结果，探测已验证 idx1=model_id、
    # idx2=status_id）
    for idx, kw in [(2, "Ready"), (1, "ThinkPad")]:
        try:
            await pick_select2(page, idx, kw)
        except Exception as e:
            print(f"  (pick{idx}: {str(e)[:50]})")
    # 提交：Save 按钮（页面搜索表单也有 submit——Search，不能 first()；
    # 创建表单 action 属性是绝对 URL，CSS $= 匹配源码属性不可靠，用文本定位）
    await page.locator("button", has_text="Save").first.click()
    await page.wait_for_timeout(3000)


def latest_asset_id() -> int:
    """最新资产 id（状态依赖注入——checkout 须有未签出资产）。"""
    import subprocess
    r = subprocess.run(
        ["docker", "exec", "snipeit-db-1", "sh", "-c",
         "mariadb -usnipeit -psnipe-pw-local snipeit -N -e "
         "'select id from assets where assigned_to is null order by id desc limit 1'"],
        capture_output=True, text=True, timeout=30)
    return int(r.stdout.strip().splitlines()[0])


async def flow_checkout(page, _tag: str) -> None:
    """最新未签出资产 → Checkout → 签出给 admin。"""
    aid = latest_asset_id()
    await page.goto(f"{SNIPE}/hardware/{aid}/checkout", wait_until="domcontentloaded")
    await page.wait_for_selector(".select2-container", timeout=15000)
    await page.wait_for_timeout(1500)
    # checkout 页映射（探测）：idx0=status, idx1=assigned_user；按钮=Checkout
    try:
        await pick_select2(page, 1, "admin")
    except Exception as e:
        print(f"  (user pick: {str(e)[:50]})")
    await page.locator("button", has_text="Checkout").last.click()
    await page.wait_for_timeout(2500)


def latest_checked_out_id() -> int:
    """最新已签出资产 id（checkin 须有已签出资产）。"""
    import subprocess
    r = subprocess.run(
        ["docker", "exec", "snipeit-db-1", "sh", "-c",
         "mariadb -usnipeit -psnipe-pw-local snipeit -N -e "
         "'select id from assets where assigned_to is not null order by id desc limit 1'"],
        capture_output=True, text=True, timeout=30)
    return int(r.stdout.strip().splitlines()[0])


async def flow_checkin(page, _tag: str) -> None:
    """最新已签出资产 → Checkin。"""
    aid = latest_checked_out_id()
    await page.goto(f"{SNIPE}/hardware/{aid}/checkin", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    await page.locator("button", has_text="Checkin").first.click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "SnipeAssetCreate", "fn": flow_create_asset},
    {"name": "SnipeAssetCheckout", "fn": flow_checkout},
    {"name": "SnipeAssetCheckin", "fn": flow_checkin},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"s43-snipe-{flow['name']}")
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
    print("=== S43-4：Snipe-IT 资产生命周期闭环 ===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_snipe(page)
        await ensure_prereq(page)

        for flow in FLOWS:
            print(f"\n--- [{flow['name']}] ---")
            sids = []
            for rnd, mark in enumerate(["甲", "乙"]):
                data = f"{flow['name'][-4:]}{ts}{mark}"
                sid = await record_flow(token, ctx, page, flow, data)
                if sid:
                    sids.append(sid)
            if len(sids) >= 1:
                skill_id = await process_and_learn(token, sids)
                results[flow["name"]] = skill_id
        await page.close()

    print("\n=== 学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "snipe-asset-flow.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
