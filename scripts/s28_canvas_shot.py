"""S28 画布 UI v2 截图：加载预置流水线展示卡片节点+贝塞尔连线。"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint28" / "screenshots"
PW = os.environ.get("S21_ADMIN_PW", "")


async def main():
    if not PW:
        raise SystemExit("need S21_ADMIN_PW")
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 960})
        await page.goto(f"{BASE}/login")
        await page.fill("[data-testid=login-username]", "admin")
        await page.fill("[data-testid=login-password]", PW)
        await page.click("[data-testid=login-submit]")
        await page.wait_for_url(f"{BASE}/dashboard", timeout=10_000)

        await page.goto(f"{BASE}/canvas")
        await page.wait_for_selector("[data-testid=canvas-select]", timeout=10_000)
        await page.select_option("[data-testid=canvas-select]", "1")
        await page.wait_for_timeout(1000)
        await page.screenshot(path=str(OUT / "03-canvas-v2.png"))
        await browser.close()
        print("saved 03-canvas-v2.png")


asyncio.run(main())
