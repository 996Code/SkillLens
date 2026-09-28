"""S28 UI v2 截图：仪表盘（统计卡+趋势+环形+活动流）+ 技能搜索过滤。"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint28" / "screenshots"
ADMIN_PW = os.environ.get("S21_ADMIN_PW", "")


async def main() -> None:
    if not ADMIN_PW:
        raise SystemExit("需要 S21_ADMIN_PW")
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 960})
        await page.goto(f"{BASE}/login")
        await page.fill("[data-testid=login-username]", "admin")
        await page.fill("[data-testid=login-password]", ADMIN_PW)
        await page.click("[data-testid=login-submit]")
        await page.wait_for_url(f"{BASE}/dashboard", timeout=10_000)
        await page.wait_for_selector("[data-testid=stat-row]", timeout=10_000)
        await page.wait_for_timeout(800)
        await page.screenshot(path=str(OUT / "01-dashboard.png"))

        # 搜索过滤
        await page.goto(f"{BASE}/skills")
        await page.wait_for_selector("[data-testid=filter-bar]", timeout=10_000)
        await page.fill("[data-testid=skill-search]", "Save")
        await page.wait_for_timeout(500)
        await page.screenshot(path=str(OUT / "02-skills-search.png"))

        await browser.close()
        print("saved:", *[q.name for q in sorted(OUT.glob("*.png"))], sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main())
