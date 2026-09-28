import asyncio, os
from pathlib import Path
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint29" / "screenshots"
PW = os.environ.get("S21_ADMIN_PW", "")

async def main():
    if not PW: raise SystemExit("need S21_ADMIN_PW")
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
        await page.wait_for_selector(".vue-flow__node", timeout=10_000)
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "01-canvas-vueflow.png"))
        await browser.close()
        print("saved 01-canvas-vueflow.png")

asyncio.run(main())
