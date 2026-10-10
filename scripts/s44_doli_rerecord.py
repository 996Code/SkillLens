"""s44 跟进：重录 Dolibarr 合作伙伴创建（action=create 干净流）。

背景：182-185/188 旧录制 url 带 __ID__ 占位（录制脱 id 产物）——
goto 落视图态无表单，fill miss（demo/sprint44/user-test-report.md 二.1）。
本脚本录干净创建流：goto card.php?action=create → fill name → 保存。

用法：cd server && RECORD_CDP_URL=http://127.0.0.1:9222 uv run python
../scripts/s44_doli_rerecord.py
"""
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710/api/v1"
CREATE_URL = "http://127.0.0.1:8080/societe/card.php?action=create"


async def find_service_worker(ctx):
    for _ in range(30):
        for w in ctx.service_workers:
            if "service-worker-loader" in w.url or "uploader" in w.url:
                return w
        await asyncio.sleep(1)
    raise RuntimeError("extension service worker 未找到")


async def ext_call(ctx, sw, msg: dict):
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))",
            msg)
    finally:
        await page.close()


async def flow_create_partner(page, name: str) -> None:
    await page.goto(CREATE_URL)
    await page.wait_for_timeout(3000)
    await page.fill("input[name=name]", name)
    await page.wait_for_timeout(800)
    # 创建合作方（保存）按钮
    btn = page.locator("button, input[type=submit], a.btn").filter(
        has_text="创建合作方").first
    await btn.click()
    await page.wait_for_timeout(2500)


async def process_and_learn(token: str, sid: str):
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.post(f"{SERVER}/sessions/{sid}/process")
        print(f"  process: {resp.status_code}")
        resp = await c.post(f"{SERVER}/align", json={"session_ids": [sid, sid]})
        aid = resp.json()["alignment_id"]
        skill = None
        for _ in range(3):
            resp = await c.post(f"{SERVER}/alignments/{aid}/induce")
            if resp.status_code == 200:
                skill = resp.json()
                break
        if not skill:
            print("  ! induce 失败")
            return None
        print(f"  induce: skill #{skill['id']} {skill['name']}")
        await c.post(f"{SERVER}/skills/{skill['id']}/assertions")
        return skill["id"]


async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        token = (await c.post(f"{SERVER}/auth/plugin-session")).json()["token"]
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = next((c for c in browser.contexts if c.service_workers),
                   browser.contexts[0])
        page = await ctx.new_page()
        ts = int(time.time()) % 100000
        sid_out = None
        for label in ("甲", "乙"):
            name = f"闭环客户重录{ts}{label}"
            print(f"== 录制 {name} ==")
            sw = await find_service_worker(ctx)
            r = await ext_call(ctx, sw, {"type": "START_RECORDING",
                                         "note": f"s44-doli-re{label}", "source": "demo"})
            sid = (r or {}).get("id", "")
            try:
                await flow_create_partner(page, name)
            except Exception as e:
                print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:120]}")
            await page.wait_for_timeout(1500)
            await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
            await page.wait_for_timeout(2500)
            sid_out = sid
        await page.close()
        if not sid_out:
            sys.exit("录制失败")
        skill_id = await process_and_learn(token, sid_out)
        if skill_id:
            print(f"\n重录技能就绪: #{skill_id}（换参验证：fill_name=新唯一值）")


if __name__ == "__main__":
    asyncio.run(main())
