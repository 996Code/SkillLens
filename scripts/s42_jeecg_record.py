"""S42-6：JeecgBoot 用户管理核心业务验证（ant-design-vue，第 8 目标系统）。

流程（各录 2 轮，换数据）：
- JeecgCreateUser：用户管理 → 新增 → 账号/密码/确认/姓名/手机 → 确认
- JeegSearchUser：用户管理 → 搜索账号 → 查询
- JeegEditUser：用户管理 → 行编辑 → 改姓名 → 确认

用法：cd server && uv run python ../scripts/s42_jeecg_record.py
前提：jeecg 栈在 8095；server 在 8710；live_browser 在 9222（已登录 jeecg）。
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
USER_URL = f"{JEECG}/system/user"


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


async def flow_create_user(page, data: str) -> None:
    ts = int(time.time()) % 100000
    await page.locator("button:has-text('新增')").click()
    await page.wait_for_timeout(3000)
    for sel, val in [("#form_item_username", f"sl{data}{ts}"),
                     ("#form_item_password", "Sl@123456"),
                     ("#form_item_confirmPassword", "Sl@123456"),
                     ("#form_item_realname", f"测试{data}"),
                     ("#form_item_phone", f"138{ts:05d}")]:
        await page.locator(sel).fill(val)
        await page.wait_for_timeout(2200)
    await page.locator("button:has-text('确 认')").click()
    await page.wait_for_timeout(2500)


async def flow_search_user(page, keyword: str) -> None:
    await page.locator("#top-query-form_username").fill(keyword)
    await page.wait_for_timeout(2500)
    await page.locator("button:has-text('查询')").first.click()
    await page.wait_for_timeout(2500)


async def flow_edit_user(page, new_name: str) -> None:
    # 等表格行就绪（Jeecg 表格异步加载，操作列按钮晚于行渲染）
    await page.locator(".ant-table-tbody tr").first.locator(
        "button:has-text('编辑')").wait_for(state="visible", timeout=15000)
    await page.locator(".ant-table-tbody tr").first.locator("button:has-text('编辑')").click()
    await page.wait_for_timeout(3000)
    await page.locator("#form_item_realname").fill(new_name)
    await page.wait_for_timeout(2200)
    await page.locator("button:has-text('确 认')").click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "JeegCreateUser", "fn": flow_create_user,
     "datas": ["甲", "乙"]},
    {"name": "JeegSearchUser", "fn": flow_search_user,
     "datas": ["sl甲", "sl乙"]},
    {"name": "JeegEditUser", "fn": flow_edit_user,
     "datas": ["测试改甲", "测试改乙"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}（{data[:20]}）")
    sid = await start_recording(ctx, f"jeecg-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await page.goto(USER_URL)
        await page.wait_for_timeout(4000)
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
    print("=== S42-6：JeecgBoot 用户管理验证 ===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        # 确认已登录（jeecg 会话在常驻浏览器 profile）
        await page.goto(USER_URL)
        await page.wait_for_timeout(3000)
        if "login" in page.url:
            print("  ! 未登录 jeecg——请先登录")
            await page.close()
            await browser.close()
            return

        for flow in FLOWS:
            print(f"\n--- [{flow['name']}] ---")
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

        print("\n=== JeecgBoot 学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "jeecg-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/jeecg-skills.json")
        await page.close()
        await browser.close()


asyncio.run(main())
