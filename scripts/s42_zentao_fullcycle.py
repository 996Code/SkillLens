"""S42-10：禅道全生命周期闭环——项目集→产品→项目→执行→任务→Bug→解决→关闭。

每轮走完整链（各环节用当轮新建的实体），录 2 轮 → 每个流程技能
获得 2 个会话 → 学习。状态依赖：执行须项目、任务须执行、解决须
激活 Bug、关闭须已解决 Bug。

用法：cd server && uv run python ../scripts/s42_zentao_fullcycle.py
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


async def fill_date(page, f, placeholder: str, value: str) -> None:
    dt = f.locator(f"input[placeholder='{placeholder}']")
    if await dt.count() > 0:
        await dt.fill(value)
        await dt.press("Enter")
        await page.wait_for_timeout(1800)


async def pick_option(page, f, picker_idx: int, text: str) -> None:
    await f.locator(".modal.show .picker").nth(picker_idx).click()
    await page.wait_for_timeout(1500)
    await f.locator(".picker-menu-list [class*=item], .picker-menu-list li").filter(
        has_text=text).first.click()
    await page.wait_for_timeout(1800)


async def submit_form(page, f) -> None:
    await f.locator("button[type=submit], #submit").first.click()
    await page.wait_for_timeout(4000)


async def flow_create_project(page, name: str) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=project&f=create&programID=0")
    await page.wait_for_timeout(5000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='name']").fill(name)
    await page.wait_for_timeout(2200)
    await fill_date(page, f, "计划完成", "2027-12-31")
    try:
        await submit_form(page, f)
    except Exception:
        pass  # 提交后跳转，按钮消失属正常


async def flow_create_execution(page, name: str) -> None:
    # 在最新项目下建迭代（项目 ID 由调用方注入到 name 后缀）
    pid = name.split("#")[-1]
    name = name.split("#")[0]
    await page.goto(f"{ZENTAO}/index.php?m=execution&f=create&projectID={pid}")
    await page.wait_for_timeout(5000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='name']").fill(name)
    await page.wait_for_timeout(2200)
    await fill_date(page, f, "计划完成", "2027-12-31")
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_create_task(page, name: str) -> None:
    eid = name.split("#")[-1]
    name = name.split("#")[0]
    await page.goto(f"{ZENTAO}/index.php?m=task&f=create&executionID={eid}")
    await page.wait_for_timeout(5000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='name']").fill(name)
    await page.wait_for_timeout(2200)
    await fill_date(page, f, "预计开始", "2027-01-01")
    await fill_date(page, f, "截止日期", "2027-12-31")
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_create_bug(page, title: str) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=bug&f=create&productID=1&branch=0&extra=moduleID=0")
    await page.wait_for_timeout(5000)
    await close_guide(page)
    f = biz_frame(page)
    await f.locator("input[name='title']").fill(title)
    await page.wait_for_timeout(2200)
    ver_picker = f.locator("[class*=form-group]", has_text="影响版本").locator(".picker").first
    await ver_picker.click()
    await page.wait_for_timeout(1500)
    await f.locator(".picker-menu-list [class*=item], .picker-menu-list li").filter(
        has_text="第一期构建").first.click()
    await page.wait_for_timeout(2000)
    try:
        await submit_form(page, f)
    except Exception:
        pass


async def flow_resolve_bug(page, _unused: str) -> None:
    await page.goto(f"{ZENTAO}/index.php?m=bug&f=browse&productID=1")
    await page.wait_for_timeout(6000)
    await close_guide(page)
    f = biz_frame(page)
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
    await page.goto(f"{ZENTAO}/index.php?m=bug&f=browse&productID=1")
    await page.wait_for_timeout(6000)
    await close_guide(page)
    f = biz_frame(page)
    btns = f.locator('[data-col="actions"] a[title="关闭"]')
    n = await btns.count()
    if n == 0:
        raise RuntimeError("无可关闭的 Bug")
    for i in range(n):
        if await btns.nth(i).is_enabled():
            await btns.nth(i).click()
            break
    await page.wait_for_timeout(5000)
    await f.locator(".modal.show button[type=submit]").click()
    await page.wait_for_timeout(4000)


async def latest_id(table: str, cond: str = "") -> int:
    """查禅道 DB 最新实体 ID（状态依赖注入用）。"""
    import subprocess
    out = subprocess.run(
        ["docker", "exec", "zentao", "/opt/zbox/bin/mysql", "-uroot", "-p123456",
         "zentao", "-sN", "-e", f"select max(id) from {table} {cond}"],
        capture_output=True, text=True, shell=False).stdout.strip()
    return int(out) if out else 0


FLOWS = [
    {"name": "ZentaoCreateProject", "fn": flow_create_project, "datas": None},
    {"name": "ZentaoCreateExecution", "fn": flow_create_execution, "datas": None},
    {"name": "ZentaoCreateTask", "fn": flow_create_task, "datas": None},
    {"name": "ZentaoCreateBug", "fn": flow_create_bug, "datas": None},
    {"name": "ZentaoResolveBug", "fn": flow_resolve_bug, "datas": ["a", "b"]},
    {"name": "ZentaoCloseBug", "fn": flow_close_bug, "datas": ["a", "b"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}（{str(data)[:20]}）")
    sid = await start_recording(ctx, f"zentao-full-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await flow["fn"](page, data)
    except Exception as e:
        print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:100]}")
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


async def login_zentao(page) -> None:
    await page.goto(f"{ZENTAO}/zentao/user-login.html")
    await page.wait_for_timeout(2500)
    if "login" in page.url:
        await page.locator("#account").fill("admin")
        await page.locator("input[name='password']").fill("Admin@123")
        await page.locator("#submit").click()
        await page.wait_for_timeout(3500)


async def main() -> None:
    print("=== S42-10：禅道全生命周期闭环（项目→执行→任务→Bug→解决→关闭）===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_zentao(page)

        # 两轮完整链：每轮建 项目→执行→任务→Bug，然后 解决+关闭
        sessions = {f["name"]: [] for f in FLOWS}
        for round_no in (1, 2):
            tag = "甲" if round_no == 1 else "乙"
            ts = int(time.time()) % 100000
            print(f"\n--- 第 {round_no} 轮完整链 ---")
            # 项目
            sid = await record_flow(token, ctx, page,
                {"name": "ZentaoCreateProject", "fn": flow_create_project},
                f"全链项目{tag}{ts}")
            if sid:
                sessions["ZentaoCreateProject"].append(sid)
            pid = await latest_id("zt_project")
            # 执行（挂到新项目）
            sid = await record_flow(token, ctx, page,
                {"name": "ZentaoCreateExecution", "fn": flow_create_execution},
                f"全链迭代{tag}{ts}#{pid}")
            if sid:
                sessions["ZentaoCreateExecution"].append(sid)
            eid = await latest_id("zt_project", "where type='sprint'")
            # 任务（挂到新迭代）
            sid = await record_flow(token, ctx, page,
                {"name": "ZentaoCreateTask", "fn": flow_create_task},
                f"全链任务{tag}{ts}#{eid}")
            if sid:
                sessions["ZentaoCreateTask"].append(sid)
            # Bug
            sid = await record_flow(token, ctx, page,
                {"name": "ZentaoCreateBug", "fn": flow_create_bug},
                f"全链Bug{tag}{ts}")
            if sid:
                sessions["ZentaoCreateBug"].append(sid)

        # 解决 + 关闭（各 2 轮，作用于两轮建的 Bug）
        for flow in FLOWS[4:]:
            print(f"\n--- [{flow['name']}] ---")
            for data in flow["datas"]:
                sid = await record_flow(token, ctx, page, flow, data)
                if sid:
                    sessions[flow["name"]].append(sid)

        # 学习
        print("\n=== 学习 ===")
        for flow in FLOWS:
            sids = sessions[flow["name"]]
            if len(sids) < 2:
                print(f"  {flow['name']}: 会话不足（{len(sids)}），跳过")
                continue
            skill_id = await process_and_learn(token, sids)
            results.append({"flow": flow["name"], "skill_id": skill_id})

        print("\n=== 全生命周期学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "zentao-fullcycle.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/zentao-fullcycle.json")
        await page.close()
        await browser.close()


asyncio.run(main())
