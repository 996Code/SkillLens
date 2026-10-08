"""生成 JeecG 登录态 storage_state（CI 服务端回放用）。

用法：cd server && uv run python scripts/jeecg_state.py
输出：.jeecg-state.json（仓库根，已 gitignore）；server 起服时带
REPLAY_STORAGE_STATE=<绝对路径> 即注入登录态。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".jeecg-state.json"
BASE = "http://127.0.0.1:8095"


async def main():
    from app.adapters.manifest import load_adapter_dir
    ms, _ = load_adapter_dir(Path("adapters"))
    m = next(x for x in ms if x.id == "jeecg")
    user, pw = m.credentials.username, m.credentials.password_literal

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.get_by_role("textbox").first.fill(user)
        await page.locator('input[type="password"]').first.fill(pw)
        await page.get_by_role("button").filter(has_text="登").first.click()
        await page.wait_for_timeout(4000)
        url = page.url
        await ctx.storage_state(path=str(OUT))
        await browser.close()
    ok = "/login" not in url
    print(f"[state] {OUT} | after-login url: {url[:60]} | {'OK' if ok else 'STILL_LOGIN'}")
    if not ok:
        sys.exit(1)


asyncio.run(main())
