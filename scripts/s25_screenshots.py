"""S25 浏览器实测截图：导出按钮 + 外部需求编号展示。

用法：cd server && S21_ADMIN_PW=... uv run python ../scripts/s25_screenshots.py
"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint25" / "screenshots"
ADMIN_PW = os.environ.get("S21_ADMIN_PW", "")


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

        # 导出按钮（skill 8 详情页脚）
        await page.goto(f"{BASE}/skills/8")
        await page.wait_for_selector("[data-testid=export-playwright-btn]")
        await page.locator("footer.replay-cta").scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(OUT / "01-export-button.png"))

        await browser.close()
        print("saved:", *[q.name for q in sorted(OUT.glob("*.png"))], sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main())
