"""S22 浏览器实测截图：视觉回归区块（基线/最近回放并排 + 差异统计）。

用法：cd server && S21_ADMIN_PW=... uv run python ../scripts/s22_screenshots.py
输出：demo/sprint22/screenshots/*.png（1400x960）
"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint22" / "screenshots"
ADMIN_PW = os.environ.get("S21_ADMIN_PW", "")
SKILL_ID = os.environ.get("S22_SKILL_ID", "8")


async def main() -> None:
    if not ADMIN_PW:
        raise SystemExit("需要环境变量 S21_ADMIN_PW（不硬编码凭据）")
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 960})

        await page.goto(f"{BASE}/login")
        await page.fill("[data-testid=login-username]", "admin")
        await page.fill("[data-testid=login-password]", ADMIN_PW)
        await page.click("[data-testid=login-submit]")
        await page.wait_for_url(f"{BASE}/skills", timeout=10_000)

        # 视觉回归区块（含基线/最近回放并排图 + 差异统计）
        await page.goto(f"{BASE}/skills/{SKILL_ID}")
        await page.wait_for_selector("[data-testid=visual-section]")
        await page.locator("[data-testid=visual-section]").scroll_into_view_if_needed()
        await page.wait_for_timeout(600)
        await page.screenshot(path=str(OUT / "01-visual-section.png"))

        # 无基线空态（重置后）
        reset = page.locator("[data-testid=visual-reset-btn]")
        if await reset.count():
            await reset.click()
            await page.wait_for_selector("[data-testid=visual-empty]")
            await page.screenshot(path=str(OUT / "02-visual-empty.png"))

        await browser.close()
        print("saved:", *[q.name for q in sorted(OUT.glob("*.png"))], sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main())
