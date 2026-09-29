"""S42-5：禅道核心业务线验证——项目集/产品/Bug/用例（iframe 架构应用）。

禅道 22.6 综合界面把业务内容渲染在 about:blank iframe——依赖 S42 的
all_frames + SW 程序化注入。流程（各录 2 轮，换数据）：
- ZentaoCreateProgram：项目集 → 添加项目集 → 填名称 → 保存
- ZentaoCreateProduct：产品 → 添加产品 → 填名称/代号 → 保存
- ZentaoCreateBug：测试 → Bug → 创建 Bug → 填标题 → 保存
- ZentaoCreateCase：测试 → 用例 → 创建用例 → 填标题 → 保存

用法：cd server && uv run python ../scripts/s42_zentao_record.py
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
    """业务内容所在 frame（禅道综合界面 = about:blank iframe）。"""
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


async def goto_menu(page, menu: str, wait_ms: int = 4000) -> None:
    """点左侧主菜单（顶层 frame）进入模块。"""
    await page.locator("#menu a", has_text=menu).first.click()
    await page.wait_for_timeout(wait_ms)
    await close_guide(page)


async def fill_in_frame(page, selector: str, value: str, wait_ms: int = 2200) -> None:
    await biz_frame(page).locator(selector).first.fill(value)
    await page.wait_for_timeout(wait_ms)


async def flow_create_program(page, name: str) -> None:
    await goto_menu(page, "项目集")
    await biz_frame(page).get_by_text("添加项目集", exact=True).click()
    await page.wait_for_timeout(3000)
    await fill_in_frame(page, "input[name='name']", name)
    await biz_frame(page).get_by_role("button", name="保存").click()
    await page.wait_for_timeout(2500)


async def flow_create_product(page, name: str) -> None:
    await goto_menu(page, "产品")
    await page.wait_for_timeout(2000)
    await close_guide(page)
    # 产品空间空态 → 添加产品按钮
    await biz_frame(page).get_by_text("添加产品").first.click()
    await page.wait_for_timeout(3000)
    await fill_in_frame(page, "input[name='name']", name)
    await fill_in_frame(page, "input[name='code']", f"SL{int(time.time())%10000}")
    await biz_frame(page).get_by_role("button", name="保存").click()
    await page.wait_for_timeout(2500)


async def flow_create_bug(page, title: str) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=bug&f=create&productID=1&branch=0&extra=moduleID=0")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    await fill_in_frame(page, "input[name='title']", title)
    await biz_frame(page).locator("#submit, button:has-text('保存')").first.click()
    await page.wait_for_timeout(2500)


async def flow_create_case(page, title: str) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=testcase&f=create&productID=1&branch=0")
    await page.wait_for_timeout(4000)
    await close_guide(page)
    await fill_in_frame(page, "input[name='title']", title)
    await biz_frame(page).locator("#submit, button:has-text('保存')").first.click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "ZentaoCreateProgram", "fn": flow_create_program,
     "datas": ["测试项目集A1", "测试项目集A2"]},
    {"name": "ZentaoCreateProduct", "fn": flow_create_product,
     "datas": ["测试产品A1", "测试产品A2"]},
    {"name": "ZentaoCreateBug", "fn": flow_create_bug,
     "datas": ["测试Bug标题A1", "测试Bug标题A2"]},
    {"name": "ZentaoCreateCase", "fn": flow_create_case,
     "datas": ["测试用例标题A1", "测试用例标题A2"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}（{data[:20]}）")
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
    print("=== S42-5：禅道核心业务线验证（iframe 架构）===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_zentao(page)
        print(f"禅道登录: {page.url}")

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

        print("\n=== 禅道学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "zentao-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/zentao-skills.json")
        await page.close()
        await browser.close()


asyncio.run(main())
