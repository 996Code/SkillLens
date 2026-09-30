"""S42-8：禅道 Bug 状态流转链验证——先人工走通，再录制正确流程。

流程（各 2 轮，每轮作用于不同 Bug）：
- ZentaoResolveBug：Bug 列表 → 解决 → 解决方案=已解决 → 解决版本=第一期构建
  → 提交（Bug: active → resolved）
- ZentaoCloseBug：Bug 列表 → 关闭（resolved Bug）→ 提交（Bug: resolved → closed）

用法：cd server && uv run python ../scripts/s42_zentao_lifecycle.py
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
ZENTAO = "http://127.0.0.1:8082"
BUG_LIST = f"{ZENTAO}/index.php?m=bug&f=browse&productID=1"


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


def biz_frame(page):
    for f in page.frames:
        if f is not page.main_frame:
            return f
    return page.main_frame


async def close_guide(page) -> None:
    try:
        await page.get_by_text("我知道了").click(timeout=2000)
        await page.wait_for_timeout(800)
    except Exception:
        pass


async def goto_bugs(page) -> None:
    await page.goto(BUG_LIST)
    await page.wait_for_timeout(6000)
    await close_guide(page)


async def pick_option(page, f, picker_idx: int, text: str) -> None:
    """打开第 N 个可见 picker 并选指定选项。"""
    await f.locator(".modal.show .picker").nth(picker_idx).click()
    await page.wait_for_timeout(1500)
    await f.locator(".picker-menu-list [class*=item], .picker-menu-list li").filter(
        has_text=text).first.click()
    await page.wait_for_timeout(1800)


async def flow_create_bug(page, data: str) -> None:
    """正确建 Bug：标题 + 影响版本（必填 picker）→ 提交。"""
    await page.goto(f"{ZENTAO}/index.php?m=bug&f=create&productID=1&branch=0&extra=moduleID=0")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='title']").fill(data)
    await page.wait_for_timeout(2200)
    ver_picker = f.locator("[class*=form-group]", has_text="影响版本").locator(".picker").first
    await ver_picker.click()
    await page.wait_for_timeout(1500)
    await f.locator(".picker-menu-list [class*=item], .picker-menu-list li").filter(
        has_text="第一期构建").first.click()
    await page.wait_for_timeout(2000)
    await f.locator("#submit, button[type=submit]").first.click()
    await page.wait_for_timeout(4000)


async def flow_resolve_bug(page, _unused: str) -> None:
    """解决首个激活 Bug：解决方案=已解决，解决版本=第一期构建。"""
    await goto_bugs(page)
    f = biz_frame(page)
    # 首个可点（enabled）的解决按钮
    btns = f.locator('[data-col="actions"] a[title="解决"]')
    n = await btns.count()
    for i in range(n):
        if await btns.nth(i).is_enabled():
            await btns.nth(i).click()
            break
    await page.wait_for_timeout(5000)
    await pick_option(page, f, 0, "已解决")
    await pick_option(page, f, 3, "第一期构建")
    await f.locator(".modal.show button[type=submit]").click()
    await page.wait_for_timeout(4000)


async def flow_close_bug(page, _unused: str) -> None:
    """关闭首个已解决 Bug。"""
    await goto_bugs(page)
    f = biz_frame(page)
    btns = f.locator('[data-col="actions"] a[title="关闭"]')
    n = await btns.count()
    if n == 0:
        raise RuntimeError("无可关闭的 Bug（需先解决）")
    for i in range(n):
        if await btns.nth(i).is_enabled():
            await btns.nth(i).click()
            break
    await page.wait_for_timeout(5000)
    # 关闭模态框：备注可空，直接提交
    await f.locator(".modal.show button[type=submit]").click()
    await page.wait_for_timeout(4000)


FLOWS = [
    {"name": "ZentaoCreateBug", "fn": flow_create_bug,
     "datas": ["流转链Bug甲", "流转链Bug乙"]},
    {"name": "ZentaoResolveBug", "fn": flow_resolve_bug, "datas": ["a", "b"]},
    {"name": "ZentaoCloseBug", "fn": flow_close_bug, "datas": ["a", "b"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}")
    sid = await start_recording(ctx, f"zentao-{flow['name']}")
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


async def login_zentao(page) -> None:
    await page.goto(f"{ZENTAO}/zentao/user-login.html")
    await page.wait_for_timeout(2500)
    if "login" in page.url:
        await page.locator("#account").fill("admin")
        await page.locator("input[name='password']").fill("Admin@123")
        await page.locator("#submit").click()
        await page.wait_for_timeout(3500)


async def main() -> None:
    print("=== S42-8：禅道 Bug 状态流转链（先走通再录制）===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_zentao(page)

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
            results.append({"flow": flow["name"], "skill_id": skill_id})

        print("\n=== 状态流转链学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "zentao-lifecycle.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/zentao-lifecycle.json")
        await page.close()
        await browser.close()


asyncio.run(main())
