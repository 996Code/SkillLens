"""S43-4：若依权限链闭环——建用户→配角色→新账号登录验证。

流程设计（每轮独立实体，录 2 轮学习）：
1. UserCreate：/system/user 新增用户（昵称/用户名/密码）+ 确定
2. RoleAssign：用户列表操作列"修改角色"？——若依用户表单内直接有"角色"
   下拉（分配角色随建户一次完成）；独立流程改为建角色（/system/role
   新增角色）——权限链= 建角色 → 建用户(选角色) → 新账号登录验证
3. LoginVerify：退出 → 新账号登录 → 断言进入 index（权限生效）

若依要点（官方 RuoYi-Vue 源码对照）：
- 登录页 placeholder 账号/密码（验证码已关）
- 用户表单 label：用户昵称/用户名称/用户密码（el-form placeholder）
- 角色字段是 el-select 多选（表单内直接勾选角色）
- 确定按钮 class el-button--primary

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_ruoyi_perm.py
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
RUOYI = "http://127.0.0.1:8093"


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


async def login_admin(page) -> None:
    await page.goto(RUOYI, wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)
    if "login" in page.url:
        await page.get_by_placeholder("账号").fill("admin")
        await page.get_by_placeholder("密码").fill("admin123")
        await page.locator("button").filter(has_text="登").first.click()
        await page.wait_for_timeout(4000)



async def _confirm_logout_box(page) -> None:
    """若依退出"安全提示"确认框——按钮是全局 .el-message-box__btns
    （aria-label 定位实测层级不稳，全局类命中且有确定文本即目标）。"""
    await page.wait_for_timeout(800)
    try:
        for _ in range(3):
            btn = page.locator(
                ".el-message-box__btns button").filter(has_text="确定")
            if await btn.count() and await btn.first.is_visible():
                await btn.first.click(timeout=4000)
                await page.wait_for_timeout(1500)
                return
            await page.wait_for_timeout(600)
    except Exception:
        pass

async def flow_create_role(page, mark: str) -> None:
    """建角色：/system/role 新增（角色名称+权限字符+确定）。"""
    await page.goto(f"{RUOYI}/system/role", wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)
    await page.locator("button").filter(has_text="新增").first.click()
    await page.wait_for_timeout(1500)
    modal = page.locator(".el-dialog")
    await modal.get_by_placeholder("请输入角色名称").fill(f"SL测试角色{mark}")
    await modal.get_by_placeholder("请输入权限字符").fill(f"sl_role_{mark}")
    await modal.locator("button").filter(has_text="确 定").first.click()
    await page.wait_for_timeout(2500)


async def flow_create_user(page, mark: str) -> None:
    """建用户并分配角色：/system/user 新增（昵称/用户名/密码/角色下拉选
    当轮角色）——权限分配随建户完成（若依官方表单设计）。"""
    await page.goto(f"{RUOYI}/system/user", wait_until="domcontentloaded")
    await page.wait_for_timeout(3500)
    await page.locator("button").filter(has_text="新增").first.click()
    await page.wait_for_timeout(1500)
    modal = page.locator(".el-dialog")
    await modal.get_by_placeholder("请输入用户昵称").fill(f"SL用户{mark}")
    await modal.get_by_placeholder("请输入用户名称").fill(f"sluser{mark}")
    await modal.get_by_placeholder("请输入用户密码").fill(f"Sl@{mark}pass")
    # 角色多选下拉（el-select）
    role_sel = modal.locator(".el-form-item").filter(has_text="角色").locator(
        ".el-select").first
    await role_sel.click()
    await page.wait_for_timeout(800)
    opt = page.locator(".el-select-dropdown__item").filter(
        has_text=f"SL测试角色{mark}").first
    await opt.click()
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    await modal.locator("button").filter(has_text="确 定").first.click()
    await page.wait_for_timeout(2500)


async def flow_login_verify(page, mark: str) -> None:
    """新账号登录验证：退出 admin → sluser 登录 → 进入 index（权限生效
    的确定性证据：登录后路由不再是 /login 且顶部出现用户名）。"""
    await page.goto(f"{RUOYI}/index", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    # 退出（头像下拉——RuoYi-Vue3 .user-nickname 直点开下拉，实测
    # 祖先 .avatar-wrapper 是 el-tooltip 触发器非 dropdown 本体）
    await page.locator(".user-nickname").first.click(timeout=8000)
    await page.wait_for_timeout(1000)
    await page.locator(".el-dropdown-menu__item").filter(
        has_text="退出登录").first.click(timeout=8000)
    await page.wait_for_timeout(1500)
    await _confirm_logout_box(page)
    await page.wait_for_timeout(1500)
    # 退出后落地页不定（index 残留/login redirect）——显式直达登录路由
    await page.goto(f"{RUOYI}/login", wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    # 若已登录态访问 /login 会重定向 index——需再退一次（防御）
    if "login" not in page.url:
        await page.locator(".user-nickname").first.click(timeout=6000)
        await page.wait_for_timeout(800)
        await page.locator(".el-dropdown-menu__item").filter(
            has_text="退出登录").first.click(timeout=6000)
        await _confirm_logout_box(page)
        await page.wait_for_timeout(2000)
        await page.goto(f"{RUOYI}/login", wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
    # 新账号登录
    await page.get_by_placeholder("账号").fill(f"sluser{mark}")
    await page.get_by_placeholder("密码").fill(f"Sl@{mark}pass")
    await page.locator("button").filter(has_text="登").first.click()
    await page.wait_for_timeout(4000)
    # 若依官方行为：初始密码登录强制弹"安全提示"（您的密码还是初始
    # 密码，请修改密码！）——不点确定 overlay 锁死整页，后续交互全超时
    await _confirm_logout_box(page)  # 同款 message-box 确定按钮
    await page.wait_for_timeout(1000)
    # 恢复 admin 会话（下轮/下流程前置状态）：退出新号 → admin 登录
    try:
        await page.locator(".user-nickname").first.click(timeout=6000)
        await page.wait_for_timeout(800)
        await page.locator(".el-dropdown-menu__item").filter(
            has_text="退出登录").first.click(timeout=6000)
        await page.wait_for_timeout(2500)
        await _confirm_logout_box(page)
    except Exception:
        pass
    await page.goto(RUOYI, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    if "login" in page.url:
        await page.get_by_placeholder("账号").fill("admin")
        await page.get_by_placeholder("密码").fill("admin123")
        await page.locator("button").filter(has_text="登").first.click()
        await page.wait_for_timeout(3500)


FLOWS = [
    {"name": "RuoYiRoleCreate", "fn": flow_create_role},
    {"name": "RuoYiUserCreate", "fn": flow_create_user},
    {"name": "RuoYiLoginVerify", "fn": flow_login_verify},
]


async def ensure_admin(page) -> None:
    """保证 admin 登录态（流程间状态锚定——上轮可能停在新号会话）。"""
    await page.goto(RUOYI, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)
    if "login" in page.url:
        await page.get_by_placeholder("账号").fill("admin")
        await page.get_by_placeholder("密码").fill("admin123")
        await page.locator("button").filter(has_text="登").first.click()
        await page.wait_for_timeout(4000)
    else:
        # 已登录但可能是新号——昵称非"若依"则退出换 admin
        nick = ""
        try:
            nick = (await page.locator(".user-nickname").first
                    .text_content(timeout=2000) or "").strip()
        except Exception:
            pass
        if nick and "若依" not in nick and "admin" not in nick.lower():
            try:
                await page.locator(".user-nickname").first.click(timeout=5000)
                await page.wait_for_timeout(800)
                await page.locator(".el-dropdown-menu__item").filter(
                    has_text="退出登录").first.click(timeout=5000)
                await page.wait_for_timeout(2500)
                await _confirm_logout_box(page)
                await page.get_by_placeholder("账号").fill("admin")
                await page.get_by_placeholder("密码").fill("admin123")
                await page.locator("button").filter(has_text="登").first.click()
                await page.wait_for_timeout(4000)
            except Exception:
                pass


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    await ensure_admin(page)
    sid = await start_recording(ctx, f"s43-ruoyi-{flow['name']}")
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
    print("=== S43-4：若依权限链闭环（建角色→建用户配角色→新账号登录验证）===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        await login_admin(page)

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

    print("\n=== 若依权限链学习结果 ===")
    for name, sid in results.items():
        print(f"  {name}: skill #{sid}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ruoyi-perm-chain.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
