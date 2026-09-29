"""S42-5：若依多业务线验证——5 模块（字典/参数/角色/通知/用户）12 流程。

每流程录 2 轮（换数据）→ process → align → induce → assertions。
回放验证走 s42_ruoyi_replay.py（SKILL_IDS 更新为产出技能）。

用法：cd server && uv run python ../scripts/s42_ruoyi_multi.py
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


# ---------- 通用动作（对话框字段一律 .el-dialog 限定——搜索框同 placeholder） ----------

async def act_create(page, fields: dict[str, str]) -> None:
    await page.get_by_role("button", name="新增").click()
    await page.wait_for_timeout(3000)
    for ph, val in fields.items():
        await page.locator(f".el-dialog input[placeholder='{ph}']").fill(val)
        await page.wait_for_timeout(2200)
    await page.get_by_role("button", name="确 定").click()
    await page.wait_for_timeout(2500)


async def act_search(page, ph: str, keyword: str) -> None:
    await page.locator(f"input[placeholder='{ph}']").first.fill(keyword)
    await page.wait_for_timeout(2500)
    await page.get_by_role("button", name="搜索").click()
    await page.wait_for_timeout(2500)


async def act_update(page, ph: str, new_val: str) -> None:
    await page.locator(".el-table__row").nth(1).get_by_role("button", name="修改").click()
    await page.wait_for_timeout(2500)
    await page.locator(f".el-dialog input[placeholder='{ph}']").fill(new_val)
    await page.wait_for_timeout(2000)
    await page.get_by_role("button", name="确 定").click()
    await page.wait_for_timeout(2500)


async def act_delete(page, _unused: str) -> None:
    await page.locator(".el-table__row").last.get_by_role("button", name="删除").click()
    await page.wait_for_timeout(2000)
    await page.get_by_role("button", name="确定").click()
    await page.wait_for_timeout(2500)


TS = int(time.time()) % 100000

FLOWS = [
    # 字典管理：完整 CRUD
    {"name": "DictCreate", "url": "/system/dict",
     "fn": lambda p, d: act_create(p, {"请输入字典名称": d, "请输入字典类型": f"sl_{TS}"}),
     "datas": ["测试字典A1", "测试字典A2"]},
    {"name": "DictSearch", "url": "/system/dict",
     "fn": lambda p, d: act_search(p, "请输入字典名称", d),
     "datas": ["测试", "A1"]},
    {"name": "DictUpdate", "url": "/system/dict",
     "fn": lambda p, d: act_update(p, "请输入字典名称", d),
     "datas": ["测试字典A1改", "测试字典A2改"]},
    {"name": "DictDelete", "url": "/system/dict",
     "fn": act_delete, "datas": ["x", "x"]},
    # 参数管理：增 + 查
    {"name": "ConfigCreate", "url": "/system/config",
     "fn": lambda p, d: act_create(p, {"请输入参数名称": d, "请输入参数键名": f"sl.key.{TS}"}),
     "datas": ["测试参数A1", "测试参数A2"]},
    {"name": "ConfigSearch", "url": "/system/config",
     "fn": lambda p, d: act_search(p, "请输入参数名称", d),
     "datas": ["测试", "A1"]},
    # 角色管理：增 + 查
    {"name": "RoleCreate", "url": "/system/role",
     "fn": lambda p, d: act_create(p, {"请输入角色名称": d, "请输入权限字符": f"sl:{TS}"}),
     "datas": ["测试角色A1", "测试角色A2"]},
    {"name": "RoleSearch", "url": "/system/role",
     "fn": lambda p, d: act_search(p, "请输入角色名称", d),
     "datas": ["测试", "A1"]},
    # 通知公告：增 + 查
    {"name": "NoticeCreate", "url": "/system/notice",
     "fn": lambda p, d: act_create(p, {"请输入公告标题": d}),
     "datas": ["测试公告A1", "测试公告A2"]},
    {"name": "NoticeSearch", "url": "/system/notice",
     "fn": lambda p, d: act_search(p, "请输入公告标题", d),
     "datas": ["测试", "A1"]},
    # 用户管理：查 + 改昵称
    {"name": "UserSearch", "url": "/system/user",
     "fn": lambda p, d: act_search(p, "请输入用户名称", d),
     "datas": ["admin", "ry"]},
    {"name": "UserUpdate", "url": "/system/user",
     "fn": lambda p, d: act_update(p, "请输入用户昵称", d),
     "datas": ["管理员改A", "管理员改B"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}（{data[:20]}）")
    sid = await start_recording(ctx, f"ruoyi-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await page.goto(f"{RUOYI}{flow['url']}")
        await page.wait_for_timeout(2500)
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


async def login_ruoyi(page) -> None:
    await page.goto(f"{RUOYI}/login")
    await page.wait_for_timeout(2500)
    pwd = page.locator("input[type='password']")
    if await pwd.count() == 0:
        return
    await page.locator("input[placeholder='账号']").fill("admin")
    await pwd.fill("admin123")
    await page.get_by_role("button", name="登 录").click()
    await page.wait_for_timeout(4000)


async def main() -> None:
    print("=== S42-5：若依多业务线验证（5 模块 12 流程）===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_ruoyi(page)

        for flow in FLOWS:
            print(f"\n--- [{flow['name']}] {flow['url']} ---")
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

        print("\n=== 多业务线学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "ruoyi-multi-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/ruoyi-multi-skills.json")
        await page.close()
        await browser.close()


asyncio.run(main())
