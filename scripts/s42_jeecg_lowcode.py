"""S42-11：JeecgBoot 低代码平台闭环——数据字典 CRUD + 在线表单列表。

流程（各 2 轮，换数据）：
- JeegDictTypeCreate：数据字典 → 新增 → 字典名称/编码 → 确定
- JeegDictDataCreate：字典 → 字典数据 → 新增 → 标题/键值 → 确定
- JeegDictTypeSearch：字典 → 名称搜索 → 查询

用法：cd server && uv run python ../scripts/s42_jeecg_lowcode.py
"""
import asyncio
import json
import sys
import subprocess
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
JEECG = "http://127.0.0.1:8095"
DICT_URL = f"{JEECG}/system/dict"


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


def read_captcha() -> str | None:
    out = subprocess.run(["docker", "exec", "jeecg-boot-redis", "redis-cli", "--scan"],
                         capture_output=True, text=True, shell=False).stdout
    for line in out.splitlines():
        if len(line) == 36 and not line.startswith(("sys:", "prefix_")):
            val = subprocess.run(["docker", "exec", "jeecg-boot-redis", "redis-cli", "get", line],
                                 capture_output=True, text=True, shell=False).stdout.strip().strip('"')
            if val and len(val) == 4 and val.isalnum():
                return val
    return None


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


async def login_jeecg(page) -> None:
    await page.goto(f"{JEECG}/login")
    await page.wait_for_timeout(4000)
    if "login" in page.url:
        await page.locator("input[placeholder='账号']").fill("admin")
        await page.locator("input[placeholder='密码']").fill("123456")
        await page.wait_for_timeout(1000)
        code = read_captcha()
        if code:
            await page.locator("input[placeholder='验证码']").fill(code)
        await page.locator("button:has-text('登 录')").click()
        await page.wait_for_timeout(5000)


async def flow_dict_type_create(page, data: str) -> None:
    """字典类型新增：名称 + 编码 → 确定。"""
    await page.goto(DICT_URL)
    await page.wait_for_timeout(4000)
    await page.locator("button:has-text('新增')").first.click()
    await page.wait_for_timeout(3000)
    ts = int(time.time()) % 100000
    await page.locator("input[placeholder='请输入字典名称']").fill(f"闭环字典{data}")
    await page.wait_for_timeout(2000)
    await page.locator("input[placeholder='请输入字典编码']").fill(f"sl_{data}_{ts}")
    await page.wait_for_timeout(2000)
    await page.locator("button:has-text('确 认'), button:has-text('确 定')").first.click()
    await page.wait_for_timeout(3000)


async def flow_dict_data_create(page, data: str) -> None:
    """字典数据新增：字典列表 → 行"字典数据" → 新增 → 标题/键值 → 确定。"""
    await page.goto(DICT_URL)
    await page.wait_for_timeout(5000)
    # 首行操作列的"字典数据"链接
    await page.locator(".ant-table-tbody a, .ant-table-tbody button").filter(
        has_text="字典数据").first.click()
    await page.wait_for_timeout(5000)
    await page.locator("button:has-text('新增')").first.click()
    await page.wait_for_timeout(3000)
    await page.locator("input[placeholder='请输入字典标题']").fill(f"闭环项{data}")
    await page.wait_for_timeout(2000)
    await page.locator("input[placeholder='请输入字典键值']").fill(f"val_{data}")
    await page.wait_for_timeout(2000)
    await page.locator("button:has-text('确 认'), button:has-text('确 定')").first.click()
    await page.wait_for_timeout(3000)


async def flow_dict_search(page, keyword: str) -> None:
    await page.goto(DICT_URL)
    await page.wait_for_timeout(4000)
    await page.locator("input[placeholder='请输入字典名称']").fill(keyword)
    await page.wait_for_timeout(2500)
    await page.locator("button:has-text('查询')").first.click()
    await page.wait_for_timeout(3000)


FLOWS = [
    {"name": "JeegDictTypeCreate", "fn": flow_dict_type_create, "datas": ["甲", "乙"]},
    {"name": "JeegDictDataCreate", "fn": flow_dict_data_create, "datas": ["甲", "乙"]},
    {"name": "JeegDictSearch", "fn": flow_dict_search, "datas": ["闭环", "甲"]},
]


async def record_flow(token: str, ctx, page, flow, data) -> str | None:
    print(f"  录制 {flow['name']}（{data}）")
    sid = await start_recording(ctx, f"jeecg-low-{flow['name']}")
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


async def main() -> None:
    print("=== S42-11：JeecgBoot 低代码平台闭环（数据字典 CRUD）===")
    token = mint_token()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        await login_jeecg(page)

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

        print("\n=== JeecgBoot 低代码闭环学习结果 ===")
        for r in results:
            print(f"  {r['flow']}: skill #{r['skill_id']}")
        out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
        out.mkdir(parents=True, exist_ok=True)
        (out / "jeecg-lowcode.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print("结果已存 demo/sprint42/jeecg-lowcode.json")
        await page.close()
        await browser.close()


asyncio.run(main())
