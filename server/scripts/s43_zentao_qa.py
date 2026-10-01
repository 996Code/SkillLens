"""S43-4：禅道 QA 链闭环——需求→用例→测试单→执行用例。

每轮走完整链（各环节用当轮新建实体），录 2 轮 → 学习。
状态依赖：用例须所属产品；测试单须产品；执行须测试单含用例。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python scripts/s43_zentao_qa.py
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
ZENTAO = "http://127.0.0.1:8082"


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


async def login_zentao(page) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=user&f=login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    if "login" in page.url:
        await page.locator("#account").fill("admin")
        # 安全红线：凭据经环境变量注入（ZENTAO_PW），不落库不进 git
        import os
        await page.locator("input[name=password]").fill(os.environ.get("ZENTAO_PW", ""))
        await page.locator("button[type=submit], #submit").first.click()
        await page.wait_for_timeout(3000)


async def pick_option(page, f, picker_idx: int, text: str) -> None:
    await f.locator(".modal.show .picker, [class*=modal] .picker").nth(picker_idx).click()
    await page.wait_for_timeout(1200)
    await f.locator(".picker-menu-list [class*=item], .picker-menu-list li").filter(
        has_text=text).first.click()
    await page.wait_for_timeout(1500)


async def submit_form(page, f) -> None:
    await f.locator("button[type=submit], #submit").first.click()
    await page.wait_for_timeout(4000)


async def flow_create_story(page, title: str) -> None:
    """产品 1 下建需求（评审通过走默认流程外的激活略——建库即验收）。"""
    await page.goto(f"{ZENTAO}/index.php?m=story&f=create&productID=1")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='title']").fill(title)
    await page.wait_for_timeout(1500)
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_create_case(page, title: str) -> None:
    """产品 1 下建测试用例。"""
    await page.goto(f"{ZENTAO}/index.php?m=testcase&f=create&productID=1")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='title']").fill(title)
    await page.wait_for_timeout(1500)
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_create_testtask(page, name: str) -> None:
    """产品 1 下建测试单（测试单名称+构建选择）。"""
    await page.goto(f"{ZENTAO}/index.php?m=testtask&f=create&productID=1")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    f = biz_frame(page)
    name_input = f.locator("input[name='name']")
    if await name_input.count() == 0:
        # 禅道 22 表单名可能是 title
        name_input = f.locator("input[name='title']")
    await name_input.fill(name)
    await page.wait_for_timeout(1500)
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_run_case(page, _mark: str) -> None:
    """最新用例 → 执行（结果=通过）。状态依赖：用例须存在。"""
    await page.goto(f"{ZENTAO}/index.php?m=testcase&f=browse&productID=1")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    f = biz_frame(page)
    # dtable 行操作是图标链接：a[title=执行]（href m=testtask&f=runCase）
    await f.locator("a[title=执行]").first.click()
    await page.wait_for_timeout(3500)
    # 执行页结果 picker 默认已选"通过"（探测确认）——直接保存提交
    # 注意执行页在 iframe 内二次渲染，submit 控件按文本定位
    f2 = biz_frame(page)
    try:
        btn = f2.locator("button[type=submit]").last
        if await btn.count() == 0:
            btn = f2.locator("button", has_text="保存").last
        await btn.click()
        await page.wait_for_timeout(3500)
    except Exception as e:
        print(f"  (run save: {str(e)[:60]})")


FLOWS = [
    {"name": "ZentaoStoryCreate", "fn": flow_create_story},
    {"name": "ZentaoCaseCreate", "fn": flow_create_case},
    {"name": "ZentaoTesttaskCreate", "fn": flow_create_testtask},
    {"name": "ZentaoCaseRun", "fn": flow_run_case},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"s43-qa-{flow['name']}")
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
    print("=== S43-4：禅道 QA 链闭环（需求→用例→测试单→执行）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_zentao(page)

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

    print("\n=== QA 链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "zentao-qa-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
