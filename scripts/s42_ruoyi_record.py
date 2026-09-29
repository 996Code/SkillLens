"""S42：若依（RuoYi-Vue，本地 Docker 源码构建）多目标全链路业务验证。

在若依 岗位管理 上录制 CRUD 流程（经 9222 常驻浏览器 + 插件采集），
走 process → align → induce → assertions 学习管道——验证国产 ERP 泛化。

流程（各录 2 轮，换数据）：
- RuoYiCreatePost：岗位管理 → 新增 → 填名称/编码 → 确定
- RuoYiSearchPost：岗位管理 → 搜索框输入 → 搜索
- RuoYiUpdatePost：岗位管理 → 编辑首行 → 改名称 → 确定
- RuoYiDeletePost：岗位管理 → 删除首行 → 确定（副作用，回放走 shadow 门控）

用法：cd server && uv run python ../scripts/s42_ruoyi_record.py
前提：ruoyi 栈在 8093（验证码已关）；server 在 8710；live_browser 在 9222。
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
RUOYI_USER = "admin"
RUOYI_PASSWORD = "admin123"

POST_URL = f"{RUOYI}/system/post"


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


async def goto_post(page) -> None:
    await page.goto(POST_URL)
    await page.wait_for_timeout(2500)


async def flow_create(page, name: str) -> None:
    # 节奏模拟真实用户：动作间 >2.5s 停顿（超 IDLE_MS 2s），
    # 让 input 成为独立窗口锚点（否则被吞进上一窗，回放不会填值）
    await page.get_by_role("button", name="新增").click()
    await page.wait_for_timeout(3000)
    # 对话框内字段（搜索框同 placeholder，必须 .el-dialog 限定避免 strict mode 撞车）
    await page.locator(".el-dialog input[placeholder='请输入岗位名称']").fill(name)
    await page.wait_for_timeout(2500)
    await page.locator(".el-dialog input[placeholder='请输入岗位编码']").fill(f"sl_{int(time.time())%100000}")
    await page.wait_for_timeout(2000)
    await page.get_by_role("button", name="确 定").click()
    await page.wait_for_timeout(2500)


async def flow_search(page, keyword: str) -> None:
    box = page.locator("input[placeholder='请输入岗位名称']").first
    await box.fill(keyword)
    await page.wait_for_timeout(2500)
    await page.get_by_role("button", name="搜索").click()
    await page.wait_for_timeout(2500)


async def flow_update(page, new_name: str) -> None:
    # 首行是受保护岗位（按钮 disabled），用第二行
    await page.locator(".el-table__row").nth(1).get_by_role("button", name="修改").click()
    await page.wait_for_timeout(2500)
    name_input = page.locator(".el-dialog input[placeholder='请输入岗位名称']")
    await name_input.fill(new_name)
    await page.wait_for_timeout(2000)
    await page.get_by_role("button", name="确 定").click()
    await page.wait_for_timeout(2500)


async def flow_delete(page, _unused: str) -> None:
    # 删除此前创建的测试岗位（末行，非受保护）
    await page.locator(".el-table__row").last.get_by_role("button", name="删除").click()
    await page.wait_for_timeout(2000)
    await page.get_by_role("button", name="确定").click()
    await page.wait_for_timeout(2500)


FLOWS = [
    {"name": "RuoYiCreatePost", "fn": flow_create,
     "datas": ["测试岗位A1", "测试岗位A2"]},
    {"name": "RuoYiSearchPost", "fn": flow_search,
     "datas": ["测试", "A1"]},
    {"name": "RuoYiUpdatePost", "fn": flow_update,
     "datas": ["测试岗位A1改", "测试岗位A2改"]},
    {"name": "RuoYiDeletePost", "fn": flow_delete,
     "datas": ["x", "x"]},
]


async def record_flow(token: str, ctx, page, flow, data: str) -> str | None:
    print(f"  录制 {flow['name']}（数据: {data[:30]}）")
    sid = await start_recording(ctx, f"ruoyi-{flow['name']}")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await goto_post(page)
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


async def login_ruoyi(page) -> None:
    await page.goto(f"{RUOYI}/login")
    await page.wait_for_timeout(2500)
    pwd = page.locator("input[type='password']")
    if await pwd.count() == 0:
        return  # 已登录
    await page.locator("input[placeholder='账号']").fill(RUOYI_USER)
    await pwd.fill(RUOYI_PASSWORD)
    await page.get_by_role("button", name="登 录").click()
    await page.wait_for_timeout(4000)


async def main() -> None:
    print("=== S42：若依多目标全链路业务验证 ===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        await login_ruoyi(page)
        print(f"若依登录: {page.url}")

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

        print("\n=== 若依录制学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']} (sessions: {r['sessions']})")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "ruoyi-skills.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/ruoyi-skills.json")

        await page.close()
        await browser.close()


asyncio.run(main())
